import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import google.generativeai as genai
import streamlit_authenticator as stauth
import firebase_admin
from firebase_admin import credentials, firestore

# --- CONFIGURATION ---
st.set_page_config(page_title="BackTrack", page_icon="🛡️", layout="wide")

# --- CONNECT TO FIRESTORE ---
# We use a singleton function so we don't re-initialize the app every reload
@st.cache_resource
def get_db():
    # Check if already initialized to avoid "App already exists" error
    if not firebase_admin._apps:
        # Load credentials from Streamlit Secrets
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- AUTHENTICATION SETUP ---
users = st.secrets["credentials"]["usernames"]
names = st.secrets["credentials"]["names"]
passwords = st.secrets["credentials"]["passwords"]

creds_dict = {'usernames': {}}
for i, user in enumerate(users):
    creds_dict['usernames'][user] = {
        'name': names[i],
        'password': passwords[i]
    }

authenticator = stauth.Authenticate(
    creds_dict,
    "backtrack_cookie", 
    "abcdef",           
    30                  
)

authenticator.login(location='main')

if st.session_state['authentication_status'] is False:
    st.error("Username/password is incorrect")
    st.stop()
elif st.session_state['authentication_status'] is None:
    st.warning("Please enter your username and password")
    st.stop()

name = st.session_state['name']
username = st.session_state['username']

with st.sidebar:
    st.title(f"👤 {name}")
    authenticator.logout(location='sidebar') 
    st.divider()

# --- GEMINI AI ---
try:
    genai.configure(api_key=st.secrets["gemini_api_key"])
    ai_available = True
except:
    ai_available = False

# --- LOAD DATA FROM FIRESTORE ---
# We query ONLY the logs that belong to this username
docs = db.collection('logs').where('User', '==', username).stream()

# Convert Firestore documents to a list of dicts, then to DataFrame
data_list = [doc.to_dict() for doc in docs]
df = pd.DataFrame(data_list)

if not df.empty:
    # Standardize Columns
    df["Duration"] = pd.to_numeric(df["Duration"], errors='coerce').fillna(0)
    df["PainLevel"] = pd.to_numeric(df["PainLevel"], errors='coerce').fillna(0)
    df["Distance"] = pd.to_numeric(df["Distance"], errors='coerce').fillna(0.0)
    df["Weight"] = pd.to_numeric(df["Weight"], errors='coerce').fillna(0.0)
    
    # Firestore stores dates as specific objects, or strings depending on save
    # We ensure they are datetime objects for pandas
    df["Date"] = pd.to_datetime(df["Date"]) 

# --- LOAD GOALS FROM FIRESTORE ---
# We store goals in a separate collection called 'goals'
target_dist = 10.0
target_pain = 2
target_date = date(2026, 12, 31)
target_activity = "Running"

# Query the user's goal (Get the most recent one)
goal_docs = db.collection('goals').where('User', '==', username).order_by('CreatedAt', direction=firestore.Query.DESCENDING).limit(1).stream()
goal_list = [g.to_dict() for g in goal_docs]

if goal_list:
    last_goal = goal_list[0]
    target_dist = float(last_goal.get("TargetDist", 10.0))
    target_pain = int(last_goal.get("TargetPain", 2))
    target_activity = last_goal.get("TargetActivity", "Running")
    try:
        # Convert string back to date object
        target_date = datetime.strptime(last_goal.get("TargetDate", "2026-12-31"), "%Y-%m-%d").date()
    except:
        pass

# --- SIDEBAR: LOGGING ---
with st.sidebar:
    st.header("📝 New Entry")
    log_type = st.radio("Log Type", ["Activity", "Pain Check-in", "Body Weight"])
    
    with st.form("entry_form"):
        c1, c2 = st.columns(2)
        with c1: date_val = st.date_input("Date", datetime.today())
        with c2: time_val = st.time_input("Time", datetime.now().time())
            
        activity_type = ""
        context = ""
        distance = 0.0
        duration = 0
        intensity = 0
        pain_loc = ""
        pain_level = 0
        weight_val = 0.0
        
        if log_type == "Activity":
            activity_type = st.selectbox("Type", ["Running", "Cycling", "Walking", "Weights", "Yoga", "Other"])
            if activity_type in ["Running", "Cycling", "Walking"]:
                context = st.selectbox("Context", ["Outdoor", "Treadmill", "Track", "Trail", "Indoor"])
                distance = st.number_input("Dist (km)", min_value=0.0, step=0.1)
            elif activity_type == "Weights":
                context = "Gym/Weights"
            duration = st.number_input("Mins", min_value=0, step=5)
            intensity = st.slider("Intensity (1-10)", 1, 10, 5)
            
        if log_type == "Pain Check-in":
            st.markdown("### 🩺 Symptom Check")
            pain_loc = st.selectbox("Loc", ["Lower Back", "Knee", "Neck", "Abdominal", "General"])
            pain_level = st.slider("Pain (0-10)", 0, 10, 0)
            
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight")
            weight_val = st.number_input("Kg", min_value=0.0, step=0.1, format="%.1f")

        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")
        
        if submitted:
            # Create Timestamp String
            combined_dt = datetime.combine(date_val, time_val)
            timestamp_str = combined_dt.strftime("%Y-%m-%d %H:%M:%S")
            
            # Construct Dictionary for Firestore
            log_data = {
                "User": username,
                "Date": timestamp_str,
                "Type": log_type,
                "Activity": activity_type if log_type == "Activity" else "",
                "Context": context,
                "Distance": distance,
                "Duration": duration,
                "Intensity": intensity,
                "PainLoc": pain_loc,
                "PainLevel": pain_level,
                "Weight": weight_val,
                "Notes": notes,
                "CreatedAt": firestore.SERVER_TIMESTAMP # Helps with sorting later
            }
            
            # Save to 'logs' collection
            db.collection('logs').add(log_data)
            st.success("Saved to Cloud Database!")
            st.rerun()

# --- DASHBOARD ---
st.title(f"🛡️ BackTrack") 

if df.empty:
    st.info(f"Welcome {name}! Start by adding an entry in the sidebar.")
else:
    # 1. Daily Stats
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration": "sum",
        "Distance": "sum",
        "PainLevel": "max",
        "Weight": "mean"
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    # 2. Logic: Best Activity + Safety Window
    pain_map = daily_stats.set_index("Date")["PainLevel"].to_dict()
    valid_activities = []
    
    # Filter matching logs
    target_logs = df[(df["Activity"] == target_activity) & (df["Distance"] > 0)].copy()
    
    for index, row in target_logs.iterrows():
        run_date = row["Date"].date()
        dist = row["Distance"]
        p0 = pain_map.get(pd.Timestamp(run_date), 0)
        p1 = pain_map.get(pd.Timestamp(run_date) + timedelta(days=1), 0)
        p2 = pain_map.get(pd.Timestamp(run_date) + timedelta(days=2), 0)
        
        if p0 <= target_pain and p1 <= target_pain and p2 <= target_pain:
            valid_activities.append(dist)
            
    current_best = max(valid_activities) if valid_activities else 0.0

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📅 Daily Log", "🏆 Progress & Goals", "🤖 AI Analyst"])

    with tab1:
        st.subheader("Last 10 Days Activity")
        last_10 = daily_stats.sort_values("Date").tail(10)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=last_10["Date"], y=last_10["Duration"], name="Mins", marker_color='rgb(55, 83, 109)'))
        fig.add_trace(go.Scatter(x=last_10["Date"], y=last_10["PainLevel"], name="Pain", yaxis="y2", mode='lines+markers', line=dict(color='red', width=3)))
        fig.update_layout(yaxis=dict(title="Mins"), yaxis2=dict(title="Pain", overlaying="y", side="right", range=[0, 10]), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
        
        # Display Dataframe
        display_cols = ["Date", "Activity", "Distance", "Duration", "PainLevel", "Weight", "Notes"]
        # Only show cols that exist (in case of empty data)
        final_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[final_cols].sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

    with tab2:
        with st.expander("⚙️ Edit Goal Settings"):
            with st.form("goal_form"):
                st.write("Set your main target:")
                new_activity = st.selectbox("Goal Activity", ["Running", "Cycling", "Walking"], index=["Running", "Cycling", "Walking"].index(target_activity) if target_activity in ["Running", "Cycling", "Walking"] else 0)
                new_dist = st.number_input("Target Distance (km)", value=target_dist, step=0.5)
                new_pain = st.number_input("Max Allowed Pain (0-10)", value=int(target_pain), min_value=0, max_value=10)
                new_date = st.date_input("Target Date", value=target_date)
                
                if st.form_submit_button("Update Goal"):
                    # Save Goal to Firestore
                    goal_data = {
                        "User": username,
                        "TargetDist": new_dist,
                        "TargetPain": new_pain,
                        "TargetDate": str(new_date),
                        "TargetActivity": new_activity,
                        "CreatedAt": firestore.SERVER_TIMESTAMP
                    }
                    db.collection('goals').add(goal_data)
                    st.success("Updated! Refreshing...")
                    st.rerun()

        days_left = (target_date - date.today()).days
        progress_pct = min(current_best / target_dist, 1.0)
        
        st.markdown(f"### 🎯 Goal: {target_activity} {target_dist}km (Pain ≤ {target_pain})")
        
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            st.progress(progress_pct)
            st.caption(f"Best Valid {target_activity}: **{current_best} km** (No pain spike for 48hrs)")
        with c2: st.metric("Target", f"{target_dist} km")
        with c3: st.metric("Deadline", f"{days_left} Days")
        
        if current_best >= target_dist:
            st.balloons()
            st.success(f"🏆 GOAL ACHIEVED! You hit your {target_activity} target!")
            
        st.divider()
        st.subheader("📊 Weekly Volume")
        weekly = daily_stats.set_index("Date").resample('W-MON').agg({"Duration": "sum", "Distance": "sum", "PainLevel": "mean", "Weight": "mean"}).reset_index()
        fig_w = go.Figure()
        fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["Distance"], fill='tozeroy', name='Vol (km)'))
        fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["PainLevel"], mode='lines+markers', name='Avg Pain', line=dict(color='red', width=3)))
        st.plotly_chart(fig_w, use_container_width=True)

    with tab3:
        st.subheader("🤖 Physio Intelligence")
        if not ai_available:
            st.warning("⚠️ Gemini API Key missing.")
        else:
            if st.button("Generate Insights"):
                with st.spinner(f"Analyzing {target_activity} data..."):
                    try:
                        # Prepare data for AI
                        recent_data = df.sort_values("Date").tail(30).to_csv(index=False)
                        
                        prompt = f"""
                        Act as an expert physiotherapist. Analyze logs (last 30 days) for User: {username}.
                        
                        GOAL: {target_activity} {target_dist}km with Pain <= {target_pain}.
                        CURRENT BEST: {current_best}km.
                        
                        DATA:
                        {recent_data}
                        
                        TASK:
                        1. Look for DELAYED patterns: Do sessions cause pain spikes 1-2 days later?
                        2. Progress Check: Are they safely increasing distance?
                        3. Recommendation: Specific plan for next week to improve {target_activity}.
                        """
                        model = genai.GenerativeModel('gemini-flash-latest')
                        response = model.generate_content(prompt)
                        st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI Error: {e}")
