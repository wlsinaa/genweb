import streamlit as st
import pandas as pd
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Time Series", layout="wide")

# Title
st.title("MSLP Time Series from GCS Bucket")

# Initialize GCS client
# Assumes GOOGLE_APPLICATION_CREDENTIALS is set in environment or service account key is provided
client = storage.Client()
bucket_name = "walter-weather-2"
file_path = "gencast_mslp/mslp_2023071312.csv"

@st.cache_data
def load_data():
    try:
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_string()
        df = pd.read_csv(pd.io.common.StringIO(data.decode('utf-8')))
        return df
    except Exception as e:
        st.error(f"Error loading data from GCS: {e}")
        return None

# Load data
df = load_data()

if df is not None:
    # Convert Datetime to datetime object
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    
    # Calculate forecast datetime based on Time_Step
    def calculate_forecast_time(row):
        base_time = row['Datetime']
        hours_offset = row['Time_Step'] * 12  # Time_Step * 12 hours
        return base_time + timedelta(hours=hours_offset)
    
    df['Forecast_Datetime'] = df.apply(calculate_forecast_time, axis=1)
    
    # Sidebar for filtering
    st.sidebar.header("Filter Options")
    selected_samples = st.sidebar.multiselect("Select Samples", options=sorted(df['Sample'].unique()), default=[0])
    selected_lat = st.sidebar.slider("Latitude", min_value=float(df['Latitude'].min()), max_value=float(df['Latitude'].max()), value=float(df['Latitude'].min()))
    selected_lon = st.sidebar.slider("Longitude", min_value=float(df['Longitude'].min()), max_value=float(df['Longitude'].max()), value=float(df['Longitude'].min()))
    
    # Filter data
    filtered_df = df[(df['Sample'].isin(selected_samples)) & 
                    (df['Latitude'] == selected_lat) & 
                    (df['Longitude'] == selected_lon)]
    
    if not filtered_df.empty:
        # Plot time series for each sample
        fig = px.line(filtered_df, x='Forecast_Datetime', y='MSLP', color='Sample',
                      title=f"MSLP Time Series (Lat: {selected_lat}, Lon: {selected_lon})",
                      labels={'Forecast_Datetime': 'Date', 'MSLP': 'Mean Sea Level Pressure (Pa)'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No data available for the selected filters.")
else:
    st.error("Failed to load data. Check GCS bucket permissions or file path.")