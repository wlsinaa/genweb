import streamlit as st
import pandas as pd
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os
import re

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Time Series", layout="wide")

# Title
st.title("MSLP Time Series from GCS Bucket")

# Initialize GCS client
client = storage.Client()
bucket_name = "walter-weather-2"
prefix = "gencast_mslp/"

@st.cache_data
def list_csv_files():
    try:
        bucket = client.get_bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)
        # Match files like mslp_%Y%m%d12.csv or mslp_%Y%m%d00.csv
        pattern = r"mslp_\d{8}(12|00)\.csv$"
        csv_files = [blob.name for blob in blobs if re.match(pattern, blob.name.split('/')[-1])]
        # Extract dates from file names (e.g., 2023071312 -> 2023-07-13 12:00)
        dates = []
        for file in csv_files:
            date_str = file.split('/')[-1].replace('mslp_', '').replace('.csv', '')
            date = datetime.strptime(date_str, '%Y%m%d%H')
            dates.append((file, date.strftime('%Y-%m-%d %H:%M')))
        return sorted(dates, key=lambda x: x[1])  # Sort by date
    except Exception as e:
        st.error(f"Error listing files from GCS: {e}")
        return []

@st.cache_data
def load_data(file_path):
    try:
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_string()
        df = pd.read_csv(pd.io.common.StringIO(data.decode('utf-8')))
        return df
    except Exception as e:
        st.error(f"Error loading data from GCS: {e}")
        return None

# List available CSV files
csv_files = list_csv_files()

if csv_files:
    # Sidebar for filtering
    st.sidebar.header("Filter Options")
    
    # Date selection
    date_options = [date for _, date in csv_files]
    selected_date = st.sidebar.selectbox("Select Date", options=date_options)
    selected_file = next(file for file, date in csv_files if date == selected_date)
    
    # Aggregation method selection
    agg_method = st.sidebar.selectbox("Aggregation Method", options=["Mean", "Median", "25th Percentile", "75th Percentile"])
    
    # Sample selection
    df = load_data(selected_file)
    if df is not None:
        all_samples = sorted(df['Sample'].unique())
        selected_samples = st.sidebar.multiselect("Select Samples", options=all_samples, default=all_samples)
        
        # Convert Datetime to datetime object
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        
        # Calculate forecast datetime based on Time_Step
        def calculate_forecast_time(row):
            base_time = row['Datetime']
            hours_offset = (int(row['Time_Step']) + 1) * 12
            return base_time + timedelta(hours=hours_offset)
        
        df['Forecast_Datetime'] = df.apply(calculate_forecast_time, axis=1)
        
        # Filter data by samples
        filtered_df = df[df['Sample'].isin(selected_samples)]
        
        if not filtered_df.empty:
            # Aggregate MSLP based on selected method
            if agg_method == "Mean":
                agg_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].mean().reset_index()
                agg_label = "Mean MSLP"
            elif agg_method == "Median":
                agg_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].median().reset_index()
                agg_label = "Median MSLP"
            elif agg_method == "25th Percentile":
                agg_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].quantile(0.25).reset_index()
                agg_label = "25th Percentile MSLP"
            else:  # 75th Percentile
                agg_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].quantile(0.75).reset_index()
                agg_label = "75th Percentile MSLP"
            
            # Plot time series for all selected samples
            fig = px.line(agg_df, x='Forecast_Datetime', y='MSLP', color='Sample',
                          title=f"{agg_label} Time Series (Selected Samples, Date: {selected_date})",
                          labels={'Forecast_Datetime': 'Date', 'MSLP': f'{agg_label} (Pa)'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No data available for the selected samples.")
    else:
        st.error("Failed to load data for the selected date. Check GCS bucket permissions or file path.")
else:
    st.error("No matching CSV files found in GCS bucket. Check bucket and file path.")