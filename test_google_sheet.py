import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets scope
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

# Load your credentials
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Open your sheet
sheet = client.open("Trilokana Marketing Bot Data").sheet1  # Replace with your sheet name

# Test adding a row
sheet.append_row(["Test Name", "test@gmail.com", "1234567890", "This is a test query"])

# Print all records
records = sheet.get_all_records()
print(records)
