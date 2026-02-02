
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURATION ---
st.set_page_config(page_title="PhysioTracker", layout="wide")

# --- CONNECT TO GOOGLE SHEETS ---
def get_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("physio_logs").sheet1
        return sheet
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

sheet = get_data()
if sheet:
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    # --- 🧹 DATA CLEANING BLOCK (The Fix) ---
    # This forces the columns to be numbers. If it finds text (""), it turns it into 0.
    if not df.empty:
        df["Duration (min)"] = pd.to_numeric(df["Duration (min)"], errors='coerce').fillna(0)
        df["Pain Level (0-10)"] = pd.to_numeric(df["Pain Level (0-10)"], errors='coerce').fillna(0)
        df["Distance (km)"] = pd.to_numeric(df["Distance (km)"], errors='coerce').fillna(0.0)
else:
    df = pd.DataFrame()

# --- SIDEBAR: LOGGING ---
with st.sidebar:
    st.header("📝 New Entry")
    
    log_type = st.radio("What do you want to log?", ["Activity", "Pain Check-in"])
    
    with st.form("entry_form"):
        date_val = st.date_input("Date", datetime.today())
        
        # Default values
        activity_type = ""
        context = ""
        distance = 0.0
        duration = 0
        intensity = 0
        pain_loc = ""
        pain_level = 0
        
        if log_type == "Activity":
            activity_type = st.selectbox("Activity Type", ["Running", "Cycling", "Weights", "Yoga", "Other"])
            
            if activity_type in ["Running", "Cycling"]:
                context = st.selectbox("Context", ["Outdoor", "Treadmill", "Track", "Trail"])
                distance = st.number_input("Distance (km)", min_value=0.0, step=0.1)
            elif activity_type == "Weights":
                context = "Gym/Weights"
                st.caption("ℹ️ Add weight details in Notes below.")
            
            duration = st.number_input("Duration (min)", min_value=0, step=5)
            intensity = st.slider("Intensity (RPE 1-10)", 1, 10, 5)
            
        if log_type == "Pain Check-in":
            st.markdown("### 🩺 Symptom Check")
            pain_loc = st.selectbox("Location", ["Lower Back", "Knee", "Neck", "General"])
            pain_level = st.slider("Pain Level (0-10)", 0, 10, 0)
            activity_type = "Symptom Log"
        
        notes = st.text_area("Notes", placeholder="Details about weights, shoes, or how you feel...")
        
        submitted = st.form_submit_button("Save Entry")
        
        if submitted and sheet:
            new_row = [
                str(date_val), 
                activity_type, 
                context, 
                distance, 
                duration, 
                intensity if log_type == "Activity" else "", 
                pain_loc, 
                pain_level if log_type == "Pain Check-in" else "",
                notes
            ]
            sheet.append_row(new_row)
            st.success("Saved! Refreshing...")
            st.rerun()

# --- DASHBOARD ---
st.title("🏃 PhysioTracker")

if not df.empty:
    df["Date"] = pd.to_datetime(df["Date"])
    
    # 1. Prepare Data for Charting (Group by Day)
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration (min)": "sum",       
        "Pain Level (0-10)": "max"     
    }).reset_index()
    
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])
    daily_stats = daily_stats.sort_values("Date")

    # 2. Chart Section
    st.subheader("Last 10 Days Activity vs Pain")
    
    last_10 = daily_stats.tail(10)
    
    fig = go.Figure()
    
    # Bar Chart: Duration
    fig.add_trace(go.Bar(
        x=last_10["Date"], 
        y=last_10["Duration (min)"], 
        name="Activity Duration", 
        marker_color='rgb(55, 83, 109)'
    ))
    
    # Line Chart: Pain
    fig.add_trace(go.Scatter(
        x=last_10["Date"], 
        y=last_10["Pain Level (0-10)"], 
        name="Max Pain Level", 
        yaxis="y2", 
        mode='lines+markers',
        line=dict(color='red', width=3)
    ))
    
    fig.update_layout(
        yaxis=dict(title="Minutes Active"),
        yaxis2=dict(title="Pain Level", overlaying="y", side="right", range=[0, 10]),
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)

    # 3. Detailed History Table
    st.subheader("📋 Detailed Log")
    
    display_df = df.sort_values(by="Date", ascending=False).copy()
    display_df["Date"] = display_df["Date"].dt.strftime('%Y-%m-%d')
    
    st.dataframe(
        display_df, 
        use_container_width=True,
        hide_index=True,
        column_config={
            "Pain Level (0-10)": st.column_config.NumberColumn("Pain", format="%d/10"),
            "Intensity (1-10)": st.column_config.NumberColumn("RPE", format="%d/10"),
            "Duration (min)": st.column_config.NumberColumn("Mins"),
            "Distance (km)": st.column_config.NumberColumn("Dist (km)")
        }
    )

else:
    st.info("Start by adding an Activity or a Pain Check-in using the sidebar.")
