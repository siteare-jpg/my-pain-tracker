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

# 🛑 THE LOGIN GATE (UPDATED FOR NEW VERSION) 🛑
# We no longer pass "Login" as a name, just the location.
authenticator.login(location='main')

# We check the session state to see if it worked
if st.session_state['authentication_status'] is False:
    st.error("Username/password is incorrect")
    st.stop()
elif st.session_state['authentication_status'] is None:
    st.warning("Please enter your username and password")
    st.stop()

# If we get here, the user is logged in.
# We grab their details from the session state.
name = st.session_state['name']
username = st.session_state['username']

# --- SIDEBAR LOGOUT (UPDATED) ---
with st.sidebar:
    st.title(f"👤 {name}")
    # Updated logout command for new version
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
            new_row = [username, str(date_val), activity_type, context, distance, duration, intensity if log_type == "Activity" else "", pain_loc, pain_level if log_type
