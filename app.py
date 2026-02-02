import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import streamlit_authenticator as stauth

# --- CONFIGURATION ---
st.set_page_config(page_title="BackTrack", page_icon="🛡️", layout="wide")

# --- AUTHENTICATION SETUP ---
users = st.secrets["credentials"]["usernames"]
names = st.secrets["credentials"]["names"]
passwords = st.secrets["credentials"]["passwords"]

# Reformat credentials for the library
credentials = {'usernames': {}}
for i, user in enumerate(users):
    credentials['usernames'][user] = {
        'name': names[i],
        'password': passwords[i]
    }

authenticator = stauth.Authenticate(
    credentials,
    "backtrack_cookie", 
    "abcdef",           
    30                  
)

# 🛑 THE LOGIN GATE 🛑
authenticator.login(location='main')

if st.session_state['authentication_status'] is False:
    st.error("Username/password is incorrect")
    st.stop()
elif st.session_state['authentication_status'] is None:
    st.warning("Please enter your username and password")
    st.stop()

# User is logged in
name = st.session_state['name']
username = st.session_state['username']

# --- SIDEBAR LOGOUT ---
with st.sidebar:
    st.title(f"👤 {name}")
    authenticator.logout(location='sidebar') 
    st.divider()

# --- CONNECT TO GOOGLE SHEETS ---
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def get_log_sheet(client):
    try:
        return client.open("physio_logs").sheet1
    except:
        return None

def get_goal_sheet(client):
    try:
        sh = client.open("physio_logs")
        try:
            return sh.worksheet("goals")
        except:
            ws = sh.add_worksheet(title="goals", rows=10, cols=6)
            ws.append_row(["User", "Target Distance (km)", "Max Pain Level", "Target Date", "Activity Type"]) 
            return ws
    except:
        return None

client = get_client()
sheet = get_log_sheet(client)
goal_sheet = get_goal_sheet(client)

# --- GEMINI AI ---
try:
    genai.configure(api_key=st.secrets["gemini_api_key"])
    ai_available = True
except:
    ai_available = False

# --- LOAD & FILTER DATA ---
df = pd.DataFrame()
if sheet:
    raw_data = sheet.get_all_records()
    df_all = pd.DataFrame(raw_data)
    
    if not df_all.empty:
        # Standardize Columns
        df_all["Duration (min)"] = pd.to_numeric(df_all["Duration (min)"], errors='coerce').fillna(0)
        df_all["Pain Level (0-10)"] = pd.to_numeric(df_all["Pain Level (0-10)"], errors='coerce').fillna(0)
        df_all["Distance (km)"] = pd.to_numeric(df_all["Distance (km)"], errors='coerce').fillna(0.0)
        if "Weight (kg)" not in df_all.columns: df_all["Weight (kg)"] = 0.0
        else: df_all["Weight (kg)"] = pd.to_numeric(df_all["Weight (kg)"], errors='coerce')
        df_all["Date"] = pd.to_datetime(df_all["Date"])
        
        # Filter for current user
        if "User" in df_all.columns:
            df = df_all[df_all["User"] == username].copy()
        else:
            st.error("⚠️ Critical Error: Google Sheet missing 'User' column.")
            df = pd.DataFrame()

# --- LOAD GOALS ---
target_dist = 10.0
target_pain = 2
target_date = date(2026, 12, 31)
target_activity = "Running"

if goal_sheet:
    all_goals = goal_sheet.get_all_records()
    user_goals = [g for g in all_goals if g.get("User") == username]
    
    if user_goals:
        last_goal = user_goals[-1]
        target_dist = float(last_goal.get("Target Distance (km)", 10.0))
        target_pain = int(last_goal.get("Max Pain Level", 2))
        target_activity = last_goal.get("Activity Type", "Running")
        try:
            target_date = datetime.strptime(last_goal.get("Target Date", "2026-12-31"), "%Y-%m-%d").date()
        except:
            pass

# --- SIDEBAR: LOGGING ---
with st.sidebar:
    st.header("📝 New Entry")
    log_type = st.radio("Log Type", ["Activity", "Pain Check-in", "Body Weight"])
    
    with st.form("entry_form"):
        date_val = st.date_input("Date", datetime.today())
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
            activity_type = "Symptom Log"
            
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight")
            weight_val = st.number_input("Kg", min_value=0.0, step=0.1, format="%.1f")
            activity_type = "Weight Log"

        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")
        
        if submitted and sheet:
            # --- THE FIX: We split this into multiple lines to prevent syntax errors ---
            new_row = [
                username, 
                str(date_val), 
                activity_type, 
                context, 
                distance, 
                duration, 
                intensity if log_type == "Activity" else "", 
                pain_loc, 
                pain_level if log_type == "Pain Check-in" else "", 
                notes, 
                weight_val if log_type == "Body Weight" else ""
            ]
            # -----------------------------------------------------------------------
            sheet.append_row(new_row)
            st.success("Saved!")
            st.rerun()

# --- DASHBOARD ---
st.title(f"🛡️ BackTrack") 

if df.empty:
    st.info(f"Welcome {name}! Start by adding an entry in the sidebar.")
else:
    # 1. Daily Stats
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration (min)": "sum",
        "Distance (km)": "sum",
        "Pain Level (0-10)": "max",
        "Weight (kg)": "mean"
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    # 2. Logic: Best Activity + Safety Window
    pain_map = daily_stats.set_index("Date")["Pain Level (0-10)"].to_dict()
    valid_activities = []
    
    target_logs = df[(df["Activity Type"] == target_activity) & (df["Distance (km)"] > 0)].copy()
    
    for index, row in target_logs.iterrows():
        run_date = row["Date"]
        dist = row["Distance (km)"]
        p0 = pain_map.get(run_date, 0)
        p1 = pain_map.get(run_date + timedelta(days=1), 0)
        p2 = pain_map.get(run_date + timedelta(days=2), 0)
        
        if p0 <= target_pain and p1 <= target_pain and p2 <= target_pain:
            valid_activities.append(dist)
            
    current_best = max(valid_activities) if valid_activities else 0.0

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📅 Daily Log", "🏆 Progress & Goals", "🤖 AI Analyst"])

    with tab1:
        st.subheader("Last 10 Days Activity")
        last_10 = daily_stats.sort_values("Date").tail(10)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=last_10["Date"], y=last_10["Duration (min)"], name="Mins", marker_color='rgb(55, 83, 109)'))
        fig.add_trace(go.Scatter(x=last_10["Date"], y=last_10["Pain Level (0-10)"], name="Pain", yaxis="y2", mode='lines+markers', line=dict(color='red', width=3)))
        fig.update_layout(yaxis=dict(title="Mins"), yaxis2=dict(title="Pain", overlaying="y", side="right", range=[0, 10]), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
        
        cols = [c for c in ["Date", "Activity Type", "Distance (km)", "Duration (min)", "Pain Level (0-10)", "Weight (kg)", "Notes"] if c in df.columns]
        st.dataframe(df[cols].sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

    with tab2:
        with st.expander("⚙️ Edit Goal Settings"):
            with st.form("goal_form"):
                st.write("Set your main target:")
                # Activity Dropdown
                new_activity = st.selectbox("Goal Activity", ["Running", "Cycling", "Walking"], index=["Running", "Cycling", "Walking"].index(target_activity) if target_activity in ["Running", "Cycling", "Walking"] else 0)
                new_dist = st.number_input("Target Distance (km)", value=target_dist, step=0.5)
                new_pain = st.number_input("Max Allowed Pain (0-10)", value=int(target_pain), min_value=0, max_value=10)
                new_date = st.date_input("Target Date", value=target_date)
                
                if st.form_submit_button("Update Goal"):
                    if goal_sheet:
                        goal_sheet.append_row([username, new_dist, new_pain, str(new_date), new_activity])
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
        weekly = daily_stats.set_index("Date").resample('W-MON').agg({"Duration (min)": "sum", "Distance (km)": "sum", "Pain Level (0-10)": "mean", "Weight (kg)": "mean"}).reset_index()
        fig_w = go.Figure()
        fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["Distance (km)"], fill='tozeroy', name='Vol (km)'))
        fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["Pain Level (0-10)"], mode='lines+markers', name='Avg Pain', line=dict(color='red', width=3)))
        st.plotly_chart(fig_w, use_container_width=True)

    with tab3:
        st.subheader("🤖 Physio Intelligence")
        if not ai_available:
            st.warning("⚠️ Gemini API Key missing.")
        else:
            if st.button("Generate Insights"):
                with st.spinner(f"Analyzing {target_activity} data..."):
                    try:
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
