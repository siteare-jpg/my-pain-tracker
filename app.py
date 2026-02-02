import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="PhysioTracker", layout="wide")

# --- CONNECT TO GOOGLE SHEETS ---
# We use Streamlit Secrets to handle the private key safely
def get_data():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # Load credentials from Streamlit Secrets
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Open the sheet
    sheet = client.open("physio_logs").sheet1
    return sheet

try:
    sheet = get_data()
    # Get all records
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
except Exception as e:
    st.error(f"Could not connect to Google Sheets. Error: {e}")
    df = pd.DataFrame()

# --- SIDEBAR: DATA LOGGING ---
with st.sidebar:
    st.header("📝 Log Today")
    with st.form("entry_form"):
        date_val = st.date_input("Date", datetime.today())
        
        # Activity Inputs
        activity_type = st.selectbox("Activity", ["Running", "Cycling", "Weights", "Yoga", "Rest"])
        context = "N/A"
        distance = 0.0
        
        if activity_type in ["Running", "Cycling"]:
            context = st.selectbox("Context", ["Outdoor", "Treadmill", "Track", "Trail"])
            distance = st.number_input("Distance (km)", min_value=0.0, step=0.1)
        elif activity_type == "Weights":
            context = st.text_input("Focus (e.g. Legs)", "General")
            
        duration = st.number_input("Duration (min)", min_value=0, step=5)
        intensity = st.slider("RPE (Intensity)", 1, 10, 5)
        
        st.markdown("---")
        pain_loc = st.selectbox("Pain Location", ["Lower Back", "Knee", "Neck", "None"])
        pain_level = st.slider("Pain Level (0-10)", 0, 10, 0)
        notes = st.text_area("Notes")
        
        submitted = st.form_submit_button("Save to Cloud")
        
        if submitted:
            # Prepare row data
            new_row = [
                str(date_val), activity_type, context, distance, 
                duration, intensity, pain_loc, pain_level, notes
            ]
            # Append to Google Sheet
            sheet.append_row(new_row)
            st.success("Saved! Refreshing...")
            st.rerun()

# --- DASHBOARD ---
st.title("🏃 PhysioTracker")

if not df.empty:
    # Ensure Date is datetime
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(by="Date", ascending=True)

    # 1. 10-Day Summary
    st.subheader("Last 10 Days")
    last_10 = df.tail(10)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=last_10["Date"], y=last_10["Duration (min)"], 
        name="Duration", marker_color='rgb(55, 83, 109)'
    ))
    fig.add_trace(go.Scatter(
        x=last_10["Date"], y=last_10["Pain Level (0-10)"], 
        name="Pain", yaxis="y2", line=dict(color='red', width=4)
    ))
    fig.update_layout(
        yaxis=dict(title="Mins"),
        yaxis2=dict(title="Pain", overlaying="y", side="right", range=[0, 10]),
        margin=dict(l=0, r=0, t=30, b=0)
    )
    st.plotly_chart(fig, use_container_width=True)

    # 2. History
    st.subheader("History")
    st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)

else:
    st.info("No data yet! Use the sidebar to log your first entry.")
