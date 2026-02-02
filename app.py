
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date
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

# --- LOAD & CLEAN DATA ---
if sheet:
    raw_data = sheet.get_all_records()
    df = pd.DataFrame(raw_data)
    
    if not df.empty:
        if "User" in df.columns:
            df = df.drop(columns=["User"])

        # Clean Numeric Columns
        df["Duration (min)"] = pd.to_numeric(df["Duration (min)"], errors='coerce').fillna(0)
        df["Pain Level (0-10)"] = pd.to_numeric(df["Pain Level (0-10)"], errors='coerce').fillna(0)
        df["Distance (km)"] = pd.to_numeric(df["Distance (km)"], errors='coerce').fillna(0.0)
        
        # New Weight Column (Handle gracefully if it doesn't exist yet in old rows)
        if "Weight (kg)" not in df.columns:
            df["Weight (kg)"] = 0.0
        else:
            df["Weight (kg)"] = pd.to_numeric(df["Weight (kg)"], errors='coerce') # Keep NaNs for empty days to avoid plotting zeros
            
        df["Date"] = pd.to_datetime(df["Date"])
    else:
        df = pd.DataFrame()
else:
    df = pd.DataFrame()

# --- SIDEBAR: LOGGING ---
with st.sidebar:
    st.header("📝 New Entry")
    
    # ADDED: "Body Weight" option
    log_type = st.radio("What do you want to log?", ["Activity", "Pain Check-in", "Body Weight"])
    
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
        weight_val = 0.0
        
        # 1. Activity Logic
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
            
        # 2. Pain Logic
        if log_type == "Pain Check-in":
            st.markdown("### 🩺 Symptom Check")
            pain_loc = st.selectbox("Location", ["Lower Back", "Knee", "Neck", "General"])
            pain_level = st.slider("Pain Level (0-10)", 0, 10, 0)
            activity_type = "Symptom Log"
            
        # 3. Weight Logic (New)
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight Check")
            weight_val = st.number_input("Weight (kg)", min_value=0.0, step=0.1, format="%.1f")
            activity_type = "Weight Log"

        notes = st.text_area("Notes", placeholder="Details...")
        
        submitted = st.form_submit_button("Save Entry")
        
        if submitted and sheet:
            # We construct the row mapping to the spreadsheet columns
            # Order: Date, Type, Context, Dist, Dur, Int, PainLoc, PainLvl, Notes, WEIGHT
            new_row = [
                str(date_val), 
                activity_type, 
                context, 
                distance, 
                duration, 
                intensity if log_type == "Activity" else "", 
                pain_loc, 
                pain_level if log_type == "Pain Check-in" else "",
                notes,
                weight_val if log_type == "Body Weight" else "" # Add weight at the end
            ]
            sheet.append_row(new_row)
            st.success("Saved! Refreshing...")
            st.rerun()

# --- MAIN DASHBOARD ---
st.title("🏃 PhysioTracker")

if df.empty:
    st.info("Start by adding an Activity, Pain, or Weight entry using the sidebar.")
else:
    # --- DATA PROCESSING ---
    # Group by Day
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration (min)": "sum",
        "Distance (km)": "sum",
        "Pain Level (0-10)": "max",
        "Weight (kg)": "mean" # Average weight if multiple entries, otherwise just the value
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    tab1, tab2 = st.tabs(["📅 Daily Log", "🏆 Weekly Progress & Goals"])

    # --- TAB 1: DAILY VIEW ---
    with tab1:
        st.subheader("Last 10 Days Activity")
        last_10 = daily_stats.sort_values("Date").tail(10)
        
        fig_daily = go.Figure()
        fig_daily.add_trace(go.Bar(
            x=last_10["Date"], y=last_10["Duration (min)"], 
            name="Mins Active", marker_color='rgb(55, 83, 109)'
        ))
        fig_daily.add_trace(go.Scatter(
            x=last_10["Date"], y=last_10["Pain Level (0-10)"], 
            name="Max Pain", yaxis="y2", mode='lines+markers', line=dict(color='red', width=3)
        ))
        fig_daily.update_layout(
            yaxis=dict(title="Minutes"),
            yaxis2=dict(title="Pain Level", overlaying="y", side="right", range=[0, 10]),
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig_daily, use_container_width=True)
        
        st.markdown("### Recent Logs")
        display_df = df.sort_values(by="Date", ascending=False).copy()
        display_df["Date"] = display_df["Date"].dt.strftime('%Y-%m-%d')
        # Reorder columns for display
        cols = ["Date", "Activity Type", "Distance (km)", "Duration (min)", "Pain Level (0-10)", "Weight (kg)", "Notes"]
        # Only select columns that actually exist (to prevent errors if spreadsheet is old)
        existing_cols = [c for c in cols if c in display_df.columns]
        st.dataframe(display_df[existing_cols], use_container_width=True, hide_index=True)

    # --- TAB 2: GOALS & WEEKLY SUMMARY ---
    with tab2:
        # 1. GOAL TRACKER
        st.markdown("### 🎯 2026 Goal: 10km Run (Pain ≤ 2)")
        goal_target = 10.0
        goal_deadline = date(2026, 12, 31)
        days_left = (goal_deadline - date.today()).days
        
        pain_free_days = daily_stats[daily_stats["Pain Level (0-10)"] <= 2]
        current_best = pain_free_days["Distance (km)"].max() if not pain_free_days.empty else 0.0
        progress_pct = min(current_best / goal_target, 1.0)
        
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"**Current Best:** {current_best} km")
            st.progress(progress_pct)
        with c2: st.metric("Target", "10.0 km")
        with c3: st.metric("Time Left", f"{days_left} Days")
        
        st.divider()

        # 2. WEEKLY SUMMARY
        st.subheader("📊 Weekly Status")
        
        weekly_df = daily_stats.set_index("Date").resample('W-MON').agg({
            "Duration (min)": "sum",
            "Distance (km)": "sum",
            "Pain Level (0-10)": "mean",
            "Weight (kg)": "mean"
        }).reset_index()
        
        if len(weekly_df) > 0:
            current_week = weekly_df.iloc[-1]
            # Handle weight: if 0 (no entry), don't show it as 0
            curr_weight = current_week['Weight (kg)']
            
            # Find last week data
            last_week = weekly_df.iloc[-2] if len(weekly_df) > 1 else None
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Dist", f"{current_week['Distance (km)']} km",
                    delta=f"{current_week['Distance (km)'] - last_week['Distance (km)']} km" if last_week is not None else None)
            with col2:
                pain_diff = (current_week['Pain Level (0-10)'] - last_week['Pain Level (0-10)']) if last_week is not None else 0
                st.metric("Avg Pain", f"{current_week['Pain Level (0-10)']:.1f}",
                    delta=f"{pain_diff:.1f}", delta_color="inverse")
            with col3:
                 st.metric("Active Mins", f"{current_week['Duration (min)']} min")
            with col4:
                # Only show weight if logged
                if curr_weight > 0:
                     st.metric("Avg Weight", f"{curr_weight:.1f} kg")
                else:
                    st.metric("Avg Weight", "--")

        # 3. CHARTS
        st.markdown("#### Trends")
        
        # Chart 1: Volume vs Pain
        fig_weekly = go.Figure()
        fig_weekly.add_trace(go.Scatter(
            x=weekly_df["Date"], y=weekly_df["Distance (km)"],
            fill='tozeroy', mode='none', name='Volume (km)',
            fillcolor='rgba(0, 100, 250, 0.2)'
        ))
        fig_weekly.add_trace(go.Scatter(
            x=weekly_df["Date"], y=weekly_df["Pain Level (0-10)"],
            mode='lines+markers', name='Avg Pain',
            line=dict(color='red', width=4)
        ))
        fig_weekly.update_layout(title="Distance vs Pain", hovermode="x unified", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_weekly, use_container_width=True)
        
        # Chart 2: Weight Trend (Only if data exists)
        # Filter out 0s for the chart
        weight_data = weekly_df[weekly_df["Weight (kg)"] > 0]
        if not weight_data.empty:
            fig_weight = go.Figure()
            fig_weight.add_trace(go.Scatter(
                x=weight_data["Date"], y=weight_data["Weight (kg)"],
                mode='lines+markers', name='Weight',
                line=dict(color='green', width=2, dash='dot')
            ))
            fig_weight.update_layout(title="Weight Trend (kg)", height=300)
            st.plotly_chart(fig_weight, use_container_width=True)
