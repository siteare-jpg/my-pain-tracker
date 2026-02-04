import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="Migration Tool", page_icon="🚚")

# --- CONNECT TO FIRESTORE ---
# (Uses the same secrets you already set up)
if not firebase_admin._apps:
    key_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.title("🚚 Data Migration Tool")
st.warning("Only use this once! It copies data from CSV to Firestore.")

# --- FILE UPLOADER ---
uploaded_file = st.file_uploader("Upload your backup.csv", type=['csv'])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.write("Preview of your data:")
    st.dataframe(df.head())

    if st.button("🚀 Start Migration"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # COUNTERS
        count = 0
        total = len(df)
        
        # --- THE MIGRATION LOOP ---
        for index, row in df.iterrows():
            # 1. Clean Data & Handle Missing Values
            # We use .get() to avoid crashing if a column name is slightly different
            user = str(row.get("User", "")).strip()
            
            # Skip empty rows
            if not user or user == "nan": 
                continue

            # Date Parsing (Try multiple formats)
            date_str = str(row.get("Date", ""))
            try:
                # Try standard date
                dt_obj = pd.to_datetime(date_str).to_pydatetime()
                final_date_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            except:
                final_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Activity Type Logic
            act_type = str(row.get("Activity Type", "")).strip()
            # If activity is empty but pain is logged, mark as Symptom Log
            pain_val = pd.to_numeric(row.get("Pain Level (0-10)", 0), errors='coerce')
            if pd.isna(pain_val): pain_val = 0
            
            weight_val = pd.to_numeric(row.get("Weight (kg)", 0), errors='coerce')
            if pd.isna(weight_val): weight_val = 0.0

            log_type = "Activity"
            if act_type == "Symptom Log" or (act_type == "" and pain_val > 0):
                log_type = "Pain Check-in"
            elif act_type == "Weight Log" or (act_type == "" and weight_val > 0):
                log_type = "Body Weight"
            
            # Construct the Data Package
            doc_data = {
                "User": user,
                "Date": final_date_str,
                "Type": log_type,
                "Activity": act_type,
                "Context": str(row.get("Context", "")),
                "Distance": float(pd.to_numeric(row.get("Distance (km)", 0), errors='coerce')) if not pd.isna(pd.to_numeric(row.get("Distance (km)", 0), errors='coerce')) else 0.0,
                "Duration": int(pd.to_numeric(row.get("Duration (min)", 0), errors='coerce')) if not pd.isna(pd.to_numeric(row.get("Duration (min)", 0), errors='coerce')) else 0,
                "Intensity": int(pd.to_numeric(row.get("Intensity", 0), errors='coerce')) if not pd.isna(pd.to_numeric(row.get("Intensity", 0), errors='coerce')) else 0,
                "PainLoc": str(row.get("Loc", "")), # Note: Your sheet might use "Loc" or "Location"
                "PainLevel": int(pain_val),
                "Weight": float(weight_val),
                "Notes": str(row.get("Notes", "")),
                "CreatedAt": firestore.SERVER_TIMESTAMP
            }

            # UPLOAD TO FIREBASE
            db.collection('logs').add(doc_data)
            
            # Update Progress
            count += 1
            progress_bar.progress(count / total)
        
        status_text.success(f"✅ Success! Migrated {count} records to Cloud Database.")
        st.balloons()
