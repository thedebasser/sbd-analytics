FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy the ETL script into the image
COPY load_training_data.py apps_to_py.py . 

# Install required Python libraries
RUN pip install --no-cache-dir \
    gspread oauth2client pandas psycopg2-binary

# Default command: run the loader
ENTRYPOINT ["python", "load_training_data.py"]
