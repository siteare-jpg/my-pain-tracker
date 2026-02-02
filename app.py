import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

# --- CONFIGURATION ---
st.set_page_config(page_title="Pain Recovery Analyst", page_icon="📈", layout="wide")

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
            ws = sh.add_worksheet(title="goals", rows=10, cols=5)
            ws.append_row(["Target Distance (km)", "Max Pain Level", "Target Date"])
            ws.append_row([10.0, 2, "2026-12-31"])
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

# --- LOAD DATA ---
df = pd.DataFrame()
if sheet:
    raw_data = sheet.get_all_records()
    df = pd.DataFrame(raw_data)
    if not df.empty:
        if "User" in df.columns: df = df.drop(columns=["User"])
        
        # Clean Data
        df["Duration (min)"] = pd.to_numeric(df["Duration (min)"], errors='coerce').fillna(0)
        df["Pain Level (0-10)"] = pd.to_numeric(df["Pain Level (0-10)"], errors='coerce').fillna(0)
        df["Distance (km)"] = pd.to_numeric(df["Distance (km)"], errors='coerce').fillna(0.0)
        if "Weight (kg)" not in df.columns: df["Weight (kg)"] = 0.0
        else: df["Weight (kg)"] = pd.to_numeric(df["Weight (kg)"], errors='coerce')
        df["Date"] = pd.to_datetime(df["Date"])

# --- LOAD GOALS ---
target_dist = 10.0
target_pain = 2
target_date = date(2026, 12, 31)

if goal_sheet:
    goal_data = goal_sheet.get_all_records()
    if goal_data:
        last_goal = goal_data[-1]
        target_dist = float(last_goal.get("Target Distance (km)", 10.0))
        target_pain = int(last_goal.get("Max Pain Level", 2))
        try:
            target_date = datetime.strptime(last_goal.get("Target Date", "2026-12-31"), "%Y-%m-%d").date()
        except:
            pass

# --- SIDEBAR ---
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
            activity_type = st.selectbox("Type", ["Running", "Cycling", "Weights", "Yoga", "Other"])
            if activity_type in ["Running", "Cycling"]:
                context = st.selectbox("Context", ["Outdoor", "Treadmill", "Track", "Trail"])
                distance = st.number_input("Dist (km)", min_value=0.0, step=0.1)
            elif activity_type == "Weights":
                context = "Gym/Weights"
            duration = st.number_input("Mins", min_value=0, step=5)
            intensity = st.slider("Intensity (1-10)", 1, 10, 5)
            
        if log_type == "Pain Check-in":
            st.markdown("### 🩺 Symptom Check")
            pain_loc = st.selectbox("Loc", ["Lower Back", "Knee", "Neck", "General"])
            pain_level = st.slider("Pain (0-10)", 0, 10, 0)
            activity_type = "Symptom Log"
            
        if log_type == "Body Weight":
            st.markdown("### ⚖️ Weight")
            weight_val = st.number_input("Kg", min_value=0.0, step=0.1, format="%.1f")
            activity_type = "Weight Log"

        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")
        
        if submitted and sheet:
            new_row = [str(date_val), activity_type, context, distance, duration, intensity if log_type == "Activity" else "", pain_loc, pain_level if log_type == "Pain Check-in" else "", notes, weight_val if log_type == "Body Weight" else ""]
            sheet.append_row(new_row)
            st.success("Saved!")
            st.rerun()

# --- DASHBOARD ---
st.title("📈 Pain Recovery Analyst")

if df.empty:
    st.info("Start by adding an entry in the sidebar.")
else:
    # 1. Daily Stats
    daily_stats = df.groupby(df["Date"].dt.date).agg({
        "Duration (min)": "sum",
        "Distance (km)": "sum",
        "Pain Level (0-10)": "max",
        "Weight (kg)": "mean"
    }).reset_index()
    daily_stats["Date"] = pd.to_datetime(daily_stats["Date"])

    # 2. ADVANCED LOGIC: The "48-Hour Safety Window"
    # We need to know if a run caused pain TODAY, TOMORROW, or the NEXT DAY.
    
    # Create a simple lookup dictionary: { Date -> Max Pain that day }
    pain_map = daily_stats.set_index("Date")["Pain Level (0-10)"].to_dict()
    
    # We will verify every run
    valid_runs = []
    
    # Filter only running rows
    running_logs = df[(df["Activity Type"] == "Running") & (df["Distance (km)"] > 0)].copy()
    
    for index, row in running_logs.iterrows():
        run_date = row["Date"]
        dist = row["Distance (km)"]
        
        # Check Day 0 (Run Day), Day 1 (Next Day), Day 2 (Day After)
        # We use .get(date, 0) so if future dates don't exist yet, we assume 0 pain (benefit of doubt)
        p0 = pain_map.get(run_date, 0)
        p1 = pain_map.get(run_date + timedelta(days=1), 0)
        p2 = pain_map.get(run_date + timedelta(days=2), 0)
        
        # The strict rule: ALL three days must be <= Target Pain
        if p0 <= target_pain and p1 <= target_pain and p2 <= target_pain:
            valid_runs.append(dist)
            
    # Get the best valid run
    current_best_run = max(valid_runs) if valid_runs else 0.0

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
        st.dataframe(df.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

    with tab2:
        with st.expander("⚙️ Edit Goal Settings"):
            with st.form("goal_form"):
                st.write("Set your main target:")
                new_dist = st.number_input("Target Distance (km)", value=target_dist, step=0.5)
                new_pain = st.number_input("Max Allowed Pain (0-10)", value=int(target_pain), min_value=0, max_value=10)
                new_date = st.date_input("Target Date", value=target_date)
                if st.form_submit_button("Update Goal"):
                    if goal_sheet:
                        goal_sheet.append_row([new_dist, new_pain, str(new_date)])
                        st.success("Updated! Refreshing...")
                        st.rerun()

        days_left = (target_date - date.today()).days
        progress_pct = min(current_best_run / target_dist, 1.0)
        
        st.markdown(f"### 🎯 Goal: Run {target_dist}km (Pain ≤ {target_pain})")
        
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            st.progress(progress_pct)
            st.caption(f"Best Valid Run: **{current_best_run} km** (No pain spike for 48hrs after)")
        with c2: st.metric("Target", f"{target_dist} km")
        with c3: st.metric("Deadline", f"{days_left} Days")
        
        if current_best_run >= target_dist:
            st.balloons()
            st.success("🏆 GOAL ACHIEVED! You ran the distance without a delayed flare-up!")
            
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
                with st.spinner("Analyzing delayed responses..."):
                    try:
                        recent_data = df.sort_values("Date").tail(30).to_csv(index=False)
                        prompt = f"""
                        Act as an expert physiotherapist. Analyze logs (last 30 days) for a patient with DELAYED ONSET back pain.
                        
                        GOAL: Run {target_dist}km with Pain <= {target_pain} (Maintaining low pain for 48 hours post-run).
                        CURRENT BEST: {current_best_run}km.
                        
                        DATA:
                        {recent_data}
                        
                        TASK:
                        1. Look for DELAYED patterns: Do runs cause pain spikes 1-2 days later?
                        2. Progress Check: Are they safely increasing distance?
                        3. Recommendation: Specific plan for next week.
                        """
                        model = genai.GenerativeModel('gemini-flash-latest')
                        response = model.generate_content(prompt)
                        st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI Error: {e}")
