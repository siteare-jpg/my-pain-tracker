import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_google_auth import Authenticate
import json
import os

# --- CONFIGURATION ---
st.set_page_config(page_title="BackTrack", page_icon="🛡️", layout="wide")

# --- CONNECT TO FIRESTORE ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- GOOGLE AUTHENTICATION SETUP ---
client_config = {
    "web": {
        "client_id": st.secrets["google_auth"]["client_id"],
        "client_secret": st.secrets["google_auth"]["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [st.secrets["google_auth"]["redirect_uri"]]
    }
}

if os.path.exists("google_credentials.json"):
    os.remove("google_credentials.json")
    
with open("google_credentials.json", "w") as f:
    json.dump(client_config, f)

authenticator = Authenticate(
    secret_credentials_path="google_credentials.json",
    cookie_name="backtrack_google_cookie",
    cookie_key="random_signature_key",
    redirect_uri=st.secrets["google_auth"]["redirect_uri"],
    cookie_expiry_days=30,
)

# 🛑 LOGIN GATE (Mobile Fix) 🛑
authenticator.check_authentification()

if not st.session_state.get('connected'):
    authorization_url = authenticator.get_authorization_url()
    st.markdown(f'''
        <div style="text-align: center; margin-top: 50px;">
            <h1>Welcome to BackTrack 🛡️</h1>
            <a href="{authorization_url}" target="_self" style="
                display: inline-block;
                background-color: #4285F4;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 4px;
                font-family: sans-serif;
                font-weight: 500;
                border: 1px solid #4285F4;
                font-size: 1.1rem;
                margin-top: 20px;
            ">
                🔵 Sign in with Google
            </a>
        </div>
    ''', unsafe_allow_html=True)
    st.stop()

# --- USER IS LOGGED IN ---
user_info = st.session_state.get('user_info', {})
username = user_info.get('email') 
name = user_info.get('name')
picture = user_info.get('picture')

with st.sidebar:
    if picture:
        st.image(picture, width=50)
    st.title(f"Hi, {name.split()[0]}!")
    if st.button("Log out"):
        authenticator.logout()
    st.divider()

# --- GEMINI AI ---
try:
    genai.configure(api_key=st.secrets["gemini_api_key"])
    ai_available = True
except:
    ai_available = False

# --- LOAD DATA ---
docs = db.collection('logs').where('User', '==', username).stream()
data_list = []
for doc in docs:
    d = doc.to_dict()
    d['id'] = doc.id # Capture ID for edit/delete
    data_list.append(d)

df = pd.DataFrame(data_list)

if not df.empty:
    df["Duration"] = pd.to_numeric(df["Duration"], errors='coerce').fillna(0)
    df["PainLevel"] = pd.to_numeric(df["PainLevel"], errors='coerce').fillna(0)
    df["Distance"] = pd.to_numeric(df["Distance"], errors='coerce').fillna(0.0)
    df["Weight"] = pd.to_numeric(df["Weight"], errors='coerce').fillna(0.0)
    df["Date"] = pd.to_datetime(df["Date"]) 

# --- LOAD GOALS ---
target_dist = 10.0
target_pain = 2
target_date = date(2026, 12, 31)
target_activity = "Running"

goal_docs = db.collection('goals').where('User', '==', username).stream()
goal_list = [g.to_dict() for g in goal_docs]

if goal_list:
    goal_list.sort(key=lambda x: str(x.get('CreatedAt', '')), reverse=True)
    last_goal = goal_list[0]
    target_dist = float(last_goal.get("TargetDist", 10.0))
    target_pain = int(last_goal.get("TargetPain", 2))
    target_activity = last_goal.get("TargetActivity", "Running")
    try:
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
            
            # --- SMART DROPDOWN (History + Add New) ---
            history_locs = []
            if not df.empty and "PainLoc" in df.columns:
                history_locs = sorted([x for x in df["PainLoc"].unique() if x and pd.notna(x)])
            
            if not history_locs:
                history_locs = ["Lower Back", "Knee", "Neck", "Shoulder"]
            
            options = ["➕ Type a new one..."] + history_locs
            selected_option = st.selectbox("Loc", options)
            
            if selected_option == "➕ Type a new one...":
                pain_loc = st.text_input("Enter location:", placeholder="e.g. Shin Splints")
            else:
                pain_loc = selected_option
            # ------------------------------------

            pain_level = st.slider("Pain (0-10)", 0, 10, 0)
            
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight")
            weight_val = st.number_input("Kg", min_value=0.0, step=0.1, format="%.1f")

        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")
        
        if submitted:
            if log_type == "Pain Check-in" and not pain_loc:
                st.error("Please enter a location!")
            else:
                combined_dt = datetime.combine(date_val, time_val)
                timestamp_str = combined_dt.strftime("%Y-%m-%d %H:%M:%S")
                
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
                    "CreatedAt": firestore.SERVER_TIMESTAMP
                }
                db.collection('logs').add(log_data)
                st.success("Saved!")
                st.rerun()

# --- DASHBOARD ---
st.title(f"🛡️ BackTrack") 

if df.empty:
    st.info(f"Welcome {name}! Start by adding an entry in the sidebar.")
else:
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration": "sum",
        "Distance": "sum",
        "PainLevel": "max",
        "Weight": "mean"
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    pain_map = daily_stats.set_index("Date")["PainLevel"].to_dict()
    valid_activities = []
    
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

    tab1, tab2, tab3 = st.tabs(["📅 Daily Log", "🏆 Progress & Goals", "🤖 AI Analyst"])

    with tab1:
        st.subheader("Last 10 Days")
        last_10 = daily_stats.sort_values("Date").tail(10)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=last_10["Date"], y=last_10["Duration"], name="Mins", marker_color='rgb(55, 83, 109)'))
        fig.add_trace(go.Scatter(x=last_10["Date"], y=last_10["PainLevel"], name="Pain", yaxis="y2", mode='lines+markers', line=dict(color='red', width=3)))
        fig.update_layout(yaxis=dict(title="Mins"), yaxis2=dict(title="Pain", overlaying="y", side="right", range=[0, 10]), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
        
        display_cols = ["Date", "Activity", "Distance", "Duration", "PainLevel", "Weight", "Notes"]
        final_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[final_cols].sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

        # --- 📝 MANAGE DATA (EDIT / DELETE) ---
        st.divider()
        with st.expander("📝 Manage Data (Edit / Delete)"):
            st.write("Select an entry to edit its notes or delete it.")
            
            # 1. Create Dropdown Options
            delete_options = {}
            for index, row in df.sort_values("Date", ascending=False).iterrows():
                d_str = row['Date'].strftime('%Y-%m-%d %H:%M')
                type_str = row.get('Type', 'Unknown')
                detail_str = row.get('Activity') if row.get('Activity') else row.get('PainLoc', '')
                label = f"{d_str} | {type_str} | {detail_str}"
                delete_options[label] = row['id']
            
            selected_label = st.selectbox("Select entry:", list(delete_options.keys()))
            
            # 2. Show Edit Form if something selected
            if selected_label:
                doc_id = delete_options[selected_label]
                # Get the actual row data
                selected_row = df[df['id'] == doc_id].iloc[0]
                
                st.markdown(f"**Editing:** `{selected_label}`")
                
                # EDITABLE FIELDS
                new_notes = st.text_area("Update Notes", value=selected_row.get('Notes', ''))
                
                c1, c2, c3 = st.columns(3)
                with c1: 
                    new_dist = st.number_input("Dist (km)", value=float(selected_row.get('Distance', 0.0)), step=0.1)
                with c2: 
                    new_pain = st.number_input("Pain Level", value=int(selected_row.get('PainLevel', 0)), min_value=0, max_value=10)
                with c3:
                    new_dur = st.number_input("Duration (min)", value=int(selected_row.get('Duration', 0)), step=5)

                col_update, col_delete = st.columns([1, 4])
                
                with col_update:
                    if st.button("💾 Update Entry"):
                        db.collection('logs').document(doc_id).update({
                            "Notes": new_notes,
                            "Distance": new_dist,
                            "PainLevel": new_pain,
                            "Duration": new_dur
                        })
                        st.success("Updated!")
                        st.rerun()
                
                with col_delete:
                    if st.button("🗑️ Delete Permanently", type="primary"):
                        db.collection('logs').document(doc_id).delete()
                        st.success("Deleted!")
                        st.rerun()

    with tab2:
        with st.expander("⚙️ Edit Goal Settings"):
            with st.form("goal_form"):
                st.write("Set your main target:")
                new_activity = st.selectbox("Goal Activity", ["Running", "Cycling", "Walking"], index=["Running", "Cycling", "Walking"].index(target_activity) if target_activity in ["Running", "Cycling", "Walking"] else 0)
                new_dist = st.number_input("Target Distance (km)", value=target_dist, step=0.5)
                new_pain = st.number_input("Max Allowed Pain (0-10)", value=int(target_pain), min_value=0, max_value=10)
                new_date = st.date_input("Target Date", value=target_date)
                
                if st.form_submit_button("Update Goal"):
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
        st.progress(progress_pct)
        if current_best >= target_dist:
            st.balloons()
            st.success("🏆 GOAL ACHIEVED!")

    with tab3:
        st.subheader("🤖 Physio Intelligence")
        if not ai_available:
            st.warning("⚠️ Gemini API Key missing.")
        else:
            if st.button("Generate Insights"):
                with st.spinner(f"Analyzing {target_activity} data..."):
                    try:
                        recent_data = df.sort_values("Date").tail(30).to_csv(index=False)
                        prompt = f"Act as an expert physiotherapist. Analyze logs (last 30 days) for User: {username}.\nGOAL: {target_activity} {target_dist}km with Pain <= {target_pain}.\nCURRENT BEST: {current_best}km.\nDATA:\n{recent_data}"
                        model = genai.GenerativeModel('gemini-flash-latest')
                        response = model.generate_content(prompt)
                        st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI Error: {e}")
