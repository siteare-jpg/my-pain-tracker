import streamlit as st
import pandas as pd
import altair as alt
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_google_auth import Authenticate
import google.generativeai as genai
from datetime import datetime
import json
import os

# --- PAGE CONFIG ---
st.set_page_config(page_title="BackTrack Pain Tracker", page_icon="❤️", layout="wide")

# --- 1. SETUP & AUTHENTICATION ---
# Ensure secrets exist
if "google_auth" not in st.secrets:
    st.error("Missing [google_auth] in secrets.toml")
    st.stop()

# 🛠️ FIX: CREATE CREDENTIALS FILE FROM SECRETS 🛠️
# The library needs a physical file, so we create it from your secrets
google_auth_secrets = dict(st.secrets["google_auth"])

# Create the dictionary structure the library expects
# (It expects a "web" or "installed" key at the top level)
credentials_dict = {"web": google_auth_secrets}

# Save to a temporary file
with open("google_credentials.json", "w") as f:
    json.dump(credentials_dict, f)

# Initialize the Authenticator using the file we just created
authenticator = Authenticate(
    secret_credentials_path="google_credentials.json", 
    cookie_name='google_auth_cookie',
    cookie_key='random_secret_key',
    redirect_uri=st.secrets["google_auth"]["redirect_uri"],
    include_granted_scopes=True
)

# Check if we are already logged in
authenticator.check_authentification()

# 🛑 CUSTOM LOGIN BUTTON (Mobile Fix) 🛑
# This replaces the standard login button to force "Same Tab" opening
if not st.session_state.get('connected'):
    st.title("Welcome to BackTrack")
    st.write("Please sign in to track your recovery.")
    
    # Generate the Google Login URL manually
    authorization_url = authenticator.get_authorization_url()
    
    # Custom HTML Button that forces target="_self" (Fixes mobile popup blocker)
    st.markdown(f'''
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
            margin-top: 20px;
        ">
            🔵 Sign in with Google
        </a>
    ''', unsafe_allow_html=True)
    st.stop() # Stop here until logged in

# If we get here, we are logged in!
user_info = st.session_state.get('user_info', {})
user_email = user_info.get('email', 'Unknown User')
st.sidebar.write(f"Logged in as: **{user_email}**")
if st.sidebar.button("Log out"):
    authenticator.logout()

# --- 2. FIREBASE CONNECTION ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- 3. FETCH DATA ---
# We fetch data upfront so we can use it for the "Smart Dropdown"
logs_ref = db.collection('logs')
docs = logs_ref.where('User', '==', user_email).stream()

data = []
for doc in docs:
    d = doc.to_dict()
    d['id'] = doc.id
    data.append(d)

df = pd.DataFrame(data)

# --- 4. SIDEBAR INPUT ---
with st.sidebar:
    st.header("📝 New Entry")
    log_type = st.radio("Type", ["Pain Check-in", "Activity"], horizontal=True)

    if log_type == "Pain Check-in":
        st.markdown("### 🩺 Symptom Check")
        
        # --- SMART DROPDOWN LOGIC ---
        # 1. Get history from the dataframe
        history_locs = []
        if not df.empty and "PainLoc" in df.columns:
            # Clean list: remove blanks, duplicates, and sort
            history_locs = sorted([x for x in df["PainLoc"].unique() if x and pd.notna(x)])
        
        # 2. Add the "Type new" option at the top
        options = ["➕ Type a new one..."] + history_locs
        
        # 3. Show the dropdown
        selected_option = st.selectbox("Location", options)
        
        # 4. Handle the custom input
        if selected_option == "➕ Type a new one...":
            pain_loc = st.text_input("Enter new location:", placeholder="e.g. Lower Back")
        else:
            pain_loc = selected_option # Use the selected history item
            
        pain_level = st.slider("Pain Level (0-10)", 0, 10, 0)
        notes = st.text_area("Notes", height=80)
        
        if st.button("Save Pain Log", use_container_width=True):
            if not pain_loc:
                st.error("Please select or type a location.")
            else:
                new_log = {
                    "User": user_email,
                    "Type": "Pain",
                    "PainLoc": pain_loc,
                    "Level": pain_level,
                    "Notes": notes,
                    "Date": datetime.now()
                }
                db.collection("logs").add(new_log)
                st.success("Saved!")
                st.rerun()

    elif log_type == "Activity":
        st.markdown("### 🏃‍♂️ Activity Log")
        
        activity_name = st.text_input("Activity Name", placeholder="e.g. Physio, Walk")
        duration = st.number_input("Duration (mins)", min_value=0, step=5)
        notes = st.text_area("Notes", height=80)
        
        if st.button("Save Activity", use_container_width=True):
            if not activity_name:
                st.error("Please enter an activity name.")
            else:
                new_log = {
                    "User": user_email,
                    "Type": "Activity",
                    "Activity": activity_name,
                    "Duration": duration,
                    "Notes": notes,
                    "Date": datetime.now()
                }
                db.collection("logs").add(new_log)
                st.success("Saved!")
                st.rerun()

# --- 5. MAIN DASHBOARD ---
st.title("📊 Recovery Dashboard")

if df.empty:
    st.info("No logs found. Use the sidebar to add your first entry!")
else:
    # Cleanup Data
    df['Date'] = pd.to_datetime(df['Date'])
    df['DateStr'] = df['Date'].dt.strftime('%Y-%m-%d')
    
    # TABS
    tab1, tab2, tab3 = st.tabs(["📉 Trends", "📋 History", "🤖 AI Analyst"])
    
    with tab1:
        st.subheader("Pain Over Time")
        pain_df = df[df['Type'] == 'Pain'].sort_values('Date')
        
        if not pain_df.empty:
            chart = alt.Chart(pain_df).mark_line(point=True).encode(
                x='Date',
                y='Level',
                color='PainLoc',
                tooltip=['DateStr', 'PainLoc', 'Level', 'Notes']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        else:
            st.write("No pain logs yet.")

    with tab2:
        st.subheader("Recent Logs")
        # Display the table, sorted by newest first
        if not df.empty:
            st.dataframe(
                df[['DateStr', 'Type', 'PainLoc', 'Activity', 'Level', 'Notes']].sort_values('DateStr', ascending=False),
                use_container_width=True
            )

    with tab3:
        st.subheader("🤖 AI Physiotherapist")
        
        # Check for Gemini Key (Must be at the TOP of secrets.toml)
        if "gemini_api_key" not in st.secrets:
            st.warning("⚠️ Gemini API Key missing. Please add 'gemini_api_key' to the top of your secrets.toml file.")
        else:
            # Configure Gemini
            genai.configure(api_key=st.secrets["gemini_api_key"])
            
            if st.button("Analyze My Recovery"):
                with st.spinner("Analyzing your data..."):
                    try:
                        # 1. Prepare Data for AI
                        # Convert dataframe to CSV string for the AI to read
                        csv_data = df.to_csv(index=False)
                        
                        # 2. The Prompt
                        prompt = f"""
                        Act as an expert Physiotherapist. 
                        Here is my recovery data in CSV format:
                        {csv_data}
                        
                        Please analyze this and tell me:
                        1. What trends do you see in my pain levels?
                        2. Is there a correlation between my activities and pain spikes?
                        3. Give me 3 specific recommendations for next week.
                        """
                        
                        # 3. Call AI
                        model = genai.GenerativeModel('gemini-pro')
                        response = model.generate_content(prompt)
                        
                        # 4. Display
                        st.markdown(response.text)
                        
                    except Exception as e:
                        st.error(f"AI Error: {e}")
