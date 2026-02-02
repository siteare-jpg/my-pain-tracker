import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

# --- CONFIGURATION ---
st.set_page_config(page_title="PhysioTracker", layout="wide")

# --- CONNECT TO GOOGLE SHEETS ---
def get_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # Load credentials from Streamlit Secrets
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Open the sheet
        sheet = client.open("physio_logs").sheet1
        return sheet
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

sheet = get_data()

# --- CONFIGURE GEMINI AI ---
# We wrap this in a try block so the app doesn't crash if the key is missing
try:
    genai.configure(api_key=st.secrets["gemini_api_key"])
    ai_available = True
except:
    ai_available = False

# --- LOAD & CLEAN DATA ---
if sheet:
    raw_data = sheet.get_all_records()
    df = pd.DataFrame(raw_data)
    
    if not df.empty:
        # 1. Cleanup "User" column if it exists from previous tests
        if "User" in df.columns:
            df = df.drop(columns=["User"])

        # 2. Clean Numeric Columns (Convert text to 0)
        df["Duration (min)"] = pd.to_numeric(df["Duration (min)"], errors='coerce').fillna(0)
        df["Pain Level (0-10)"] = pd.to_numeric(df["Pain Level (0-10)"], errors='coerce').fillna(0)
        df["Distance (km)"] = pd.to_numeric(df["Distance (km)"], errors='coerce').fillna(0.0)
        
        # 3. Handle Weight Column (Create it if it doesn't exist)
        if "Weight (kg)" not in df.columns:
            df["Weight (kg)"] = 0.0
        else:
            df["Weight (kg)"] = pd.to_numeric(df["Weight (kg)"], errors='coerce')
            
        # 4. Fix Dates
        df["Date"] = pd.to_datetime(df["Date"])
    else:
        df = pd.DataFrame()
else:
    df = pd.DataFrame()

# --- SIDEBAR: LOGGING ---
with st.sidebar:
    st.header("📝 New Entry")
    
    log_type = st.radio("Log Type", ["Activity", "Pain Check-in", "Body Weight"])
    
    with st.form("entry_form"):
        date_val = st.date_input("Date", datetime.today())
        
        # Initialize default variables
        activity_type = ""
        context = ""
        distance = 0.0
        duration = 0
        intensity = 0
        pain_loc = ""
        pain_level = 0
        weight_val = 0.0
        
        # 1. Activity Inputs
        if log_type == "Activity":
            activity_type = st.selectbox("Type", ["Running", "Cycling", "Weights", "Yoga", "Other"])
            
            if activity_type in ["Running", "Cycling"]:
                context = st.selectbox("Context", ["Outdoor", "Treadmill", "Track", "Trail"])
                distance = st.number_input("Dist (km)", min_value=0.0, step=0.1)
            elif activity_type == "Weights":
                context = "Gym/Weights"
                st.caption("ℹ️ Add weight details in Notes below.")
            
            duration = st.number_input("Mins", min_value=0, step=5)
            intensity = st.slider("Intensity (1-10)", 1, 10, 5)
            
        # 2. Pain Inputs
        if log_type == "Pain Check-in":
            st.markdown("### 🩺 Symptom Check")
            pain_loc = st.selectbox("Loc", ["Lower Back", "Knee", "Neck", "General"])
            pain_level = st.slider("Pain (0-10)", 0, 10, 0)
            activity_type = "Symptom Log"
            
        # 3. Weight Inputs
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight")
            weight_val = st.number_input("Kg", min_value=0.0, step=0.1, format="%.1f")
            activity_type = "Weight Log"

        notes = st.text_area("Notes", placeholder="Details...")
        
        submitted = st.form_submit_button("Save Entry")
        
        if submitted and sheet:
            # Map inputs to columns
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
                weight_val if log_type == "Body Weight" else ""
            ]
            sheet.append_row(new_row)
            st.success("Saved!")
            st.rerun()

# --- MAIN DASHBOARD ---
st.title("🏃 PhysioTracker")

if df.empty:
    st.info("Start by adding an entry in the sidebar.")
else:
    # Aggregated Data for Charts
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration (min)": "sum",
        "Distance (km)": "sum",
        "Pain Level (0-10)": "max",
        "Weight (kg)": "mean"
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    # TABS
    tab1, tab2, tab3 = st.tabs(["📅 Daily Log", "🏆 Weekly Progress", "🤖 AI Analyst"])

    # --- TAB 1: DAILY VIEW ---
    with tab1:
        st.subheader("Last 10 Days Activity")
        last_10 = daily_stats.sort_values("Date").tail(10)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=last_10["Date"], y=last_10["Duration (min)"], name="Mins", marker_color='rgb(55, 83, 109)'))
        fig.add_trace(go.Scatter(x=last_10["Date"], y=last_10["Pain Level (0-10)"], name="Pain", yaxis="y2", mode='lines+markers', line=dict(color='red', width=3)))
        
        fig.update_layout(
            yaxis=dict(title="Mins"), 
            yaxis2=dict(title="Pain", overlaying="y", side="right", range=[0, 10]), 
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### Recent Log Entries")
        # Display raw dataframe sorted by date
        cols = [c for c in ["Date", "Activity Type", "Distance (km)", "Duration (min)", "Pain Level (0-10)", "Weight (kg)", "Notes"] if c in df.columns]
        st.dataframe(df[cols].sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

    # --- TAB 2: PROGRESS & GOALS ---
    with tab2:
        # 1. Goal Tracker
        st.markdown("### 🎯 2026 Goal: 10km (Pain ≤ 2)")
        pain_free = daily_stats[daily_stats["Pain Level (0-10)"] <= 2]
        best_run = pain_free["Distance (km)"].max() if not pain_free.empty else 0.0
        
        # Calculate goal stats
        target = 10.0
        days_left = (date(2026, 12, 31) - date.today()).days
        
        c1, c2, c3 = st.columns([2,1,1])
        with c1: 
            st.progress(min(best_run / target, 1.0))
            st.write(f"**Best Pain-Free Run:** {best_run} km")
        with c2: st.metric("Target", f"{target} km")
        with c3: st.metric("Deadline", f"{days_left} Days")
        
        st.divider()
        
        # 2. Weekly Summary
        st.subheader("📊 Weekly Trends")
        weekly = daily_stats.set_index("Date").resample('W-MON').agg({
            "Duration (min)": "sum", 
            "Distance (km)": "sum", 
            "Pain Level (0-10)": "mean", 
            "Weight (kg)": "mean"
        }).reset_index()
        
        if not weekly.empty:
            # Chart: Volume vs Pain
            fig_w = go.Figure()
            fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["Distance (km)"], fill='tozeroy', name='Vol (km)'))
            fig_w.add_trace(go.Scatter(x=weekly["Date"], y=weekly["Pain Level (0-10)"], mode='lines+markers', name='Avg Pain', line=dict(color='red', width=3)))
            fig_w.update_layout(title="Volume vs Pain", hovermode="x unified", legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_w, use_container_width=True)
            
            # Chart: Weight (if data exists)
            w_data = weekly[weekly["Weight (kg)"] > 0]
            if not w_data.empty:
                fig_weight = go.Figure()
                fig_weight.add_trace(go.Scatter(x=w_data["Date"], y=w_data["Weight (kg)"], mode='lines+markers', name='Weight', line=dict(color='green', dash='dot')))
                fig_weight.update_layout(title="Weight Trend", height=300)
                st.plotly_chart(fig_weight, use_container_width=True)

    # --- TAB 3: AI ANALYST (UPDATED WITH DEBUGGER) ---
    with tab3:
        st.subheader("🤖 Physio Intelligence")
        
        if not ai_available:
            st.warning("⚠️ Gemini API Key not found. Add `gemini_api_key` to your Streamlit Secrets.")
        else:
            # --- DEBUGGER BLOCK ---
            with st.expander("🛠️ Debug: See Available Models (Click here if AI fails)"):
                try:
                    st.write("Checking models available to your API key...")
                    model_list = []
                    for m in genai.list_models():
                        if 'generateContent' in m.supported_generation_methods:
                            model_list.append(m.name)
                            st.code(m.name)
                    if not model_list:
                        st.error("No valid models found. Check your API key permissions.")
                except Exception as e:
                    st.error(f"Error listing models: {e}")
            # ----------------------

            st.write("I will analyze your recent logs to find triggers and patterns.")
            
            if st.button("Generate Insights"):
                with st.spinner("Analyzing your data..."):
                    try:
                        # 1. Prepare Data (Last 30 days)
                        recent_data = df.sort_values("Date").tail(30).to_csv(index=False)
                        
                        # 2. The Prompt
                        prompt = f"""
                        Act as an expert physiotherapist and data scientist. 
                        Analyze the following health logs (last 30 days) for a patient with back pain.
                        
                        Columns: Date, Activity, Context, Distance, Duration, Intensity, Pain Location, Pain Level, Notes, Weight.
                        
                        DATA:
                        {recent_data}
                        
                        YOUR TASK:
                        1. Identify triggers: Look for correlations between specific activities (e.g. Treadmill vs Outdoor) and pain spikes 24-48 hours later.
                        2. Spot progress: Are they running further? Is pain decreasing?
                        3. Give 1 specific recommendation for next week.
                        
                        Keep it concise, encouraging, and use bullet points.
                        """
                        
                        # 3. Call Gemini
                        # NOTE: If this fails, check the Debug list above and replace this name!
                        model = genai.GenerativeModel('gemini-1.5-flash') 
                        response = model.generate_content(prompt)
                        
                        # 4. Display Result
                        st.markdown(response.text)
                        
                    except Exception as e:
                        st.error(f"AI Error: {e}")
                        st.info("💡 Tip: Open the 'Debug' section above to see which model names are valid for your key.")
