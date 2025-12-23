import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import os
import json
import time
from io import BytesIO
import PyPDF2
import xlsxwriter

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Invoice Extract Pro", page_icon="💎", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; background-color: #0068C9; color: white; font-weight: bold; }
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. AUTHENTICATION (Security Layer) ---
def check_password():
    """Returns `True` if the user had the correct password."""
    
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        # CHANGE "client123" TO YOUR DESIRED PASSWORD
        if st.session_state["password"] == "client123": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input("🔒 Enter Access Password", type="password", on_change=password_entered, key="password")
        return False
        
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input again.
        st.text_input("🔒 Enter Access Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
        
    else:
        # Password correct.
        return True

# Stop execution if password not correct
# REMOVE THE '#' BELOW TO ENABLE PASSWORD PROTECTION
# if not check_password():
#     st.stop()

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("💎 Pro Dashboard")
    
    # --- FIX: ROBUST KEY LOADING ---
    api_key = None
    try:
        # Try to load from secrets (Works on Cloud)
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.success("✅ API Key Loaded")
    except Exception:
        # If running locally without secrets.toml, just ignore and let user type it
        pass

    # If key wasn't found in secrets, ask user to type it
    if not api_key:
        api_key = st.text_input("🔑 Google API Key", type="password")
    
    st.markdown("### ⚙️ Engine Settings")
    model_choice = st.selectbox("Engine", ["gemini-2.5-flash", "gemini-2.0-flash"], index=0)
    
    st.info("💡 **Status:** Flawless Master-Detail Mode Active.")

# --- 4. CORE LOGIC ---

def split_pdf_into_batches(pdf_bytes, batch_size=15):
    """Splits large PDFs to avoid token limits."""
    try:
        reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        batches = []
        
        for i in range(0, total_pages, batch_size):
            writer = PyPDF2.PdfWriter()
            end_page = min(i + batch_size, total_pages)
            for page_num in range(i, end_page):
                writer.add_page(reader.pages[page_num])
            
            chunk_buffer = BytesIO()
            writer.write(chunk_buffer)
            chunk_buffer.seek(0)
            
            batches.append({"data": chunk_buffer.getvalue(), "range": f"Pages {i+1}-{end_page}"})
        return batches
    except Exception as e:
        return []

def get_gemini_response(client, model, pdf_bytes, filename, page_range="All"):
    """
    Extracts strictly hierarchical data: Parent (Invoice) -> Children (Items).
    Aggressively looks for Buyer details and General Summary.
    """
    full_prompt = f"""
    Act as a senior forensic accountant. Analyze this PDF chunk ({page_range}).
    Extract data strictly into a PARENT-CHILD hierarchy.
    
    CRITICAL EXTRACTION RULES:
    1. **Buyer_Name_Only**: Extract ONLY the Legal Company Name OR Person Name. DO NOT include address, email, or phone.
       - BAD: "Olivia Smith, 123 Street, NY"
       - GOOD: "Olivia Smith" OR "Really Great Company"
    2. **Summary**: Write a short 5-10 word summary of the WHOLE invoice (e.g., "Web Design and SEO Services").
    3. **Line Items**: Extract the physical table of goods/services.
    4. **Formatting**: Dates MUST be YYYY-MM-DD. Amounts must be floats.
    
    JSON STRUCTURE (Return a LIST of these objects):
    [
        {{
            "Invoice_ID": "string (keep zeros)",
            "Date_Issued": "YYYY-MM-DD",
            "Due_Date": "YYYY-MM-DD",
            "Seller_Name": "string",
            "Buyer_Name_Only": "string (Name ONLY, no address)",
            "Total_Amount": float,
            "Tax_Amount": float,
            "Currency": "string",
            "Bank_IBAN": "string",
            "General_Summary": "string",
            "Line_Items": [
                {{
                    "Description": "string",
                    "Quantity": float,
                    "Unit_Price": float,
                    "Line_Total": float
                }}
            ]
        }}
    ]
    """
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    full_prompt
                ],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                time.sleep(5 + (attempt * 5))
                continue
            return None
    return None

def create_flawless_excel(invoices):
    """
    Generates the Perfect Master-Detail Excel.
    Features: Grouping, Text-Forced IDs, Specific Alignment, Filters.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Invoices_Master_Detail')
        
        # --- STYLES ---
        # 1. Header (Blue, Bold, Centered)
        header_fmt = workbook.add_format({
            'bold': True, 'fg_color': '#1F4E78', 'font_color': 'white', 
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        
        # 2. Parent Row Styles (Blue Background)
        parent_left = workbook.add_format({'bold': True, 'fg_color': '#DCE6F1', 'border': 1, 'align': 'left', 'valign': 'vcenter'})
        parent_center = workbook.add_format({'bold': True, 'fg_color': '#DCE6F1', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        parent_money = workbook.add_format({'bold': True, 'fg_color': '#DCE6F1', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0.00'})
        
        # 3. Child Row Styles (White Background)
        child_left = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter', 'indent': 1})
        child_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        child_money = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0.00'})
        
        # --- HEADERS ---
        headers = [
            "Type", "Filename", "Invoice_ID", "Date", "Due Date", 
            "Seller", "Buyer", "Bank Info",
            "Item Description", "Qty", "Unit Price", "Line Total", 
            "Tax", "TOTAL PAYABLE", "Currency", "General Summary"
        ]
        
        for col, h in enumerate(headers):
            worksheet.write(0, col, h, header_fmt)
            
        # --- COLUMN WIDTHS ---
        worksheet.set_column('A:A', 10)  # Type
        worksheet.set_column('B:B', 25)  # Filename (Left)
        worksheet.set_column('C:C', 15)  # ID (Center)
        worksheet.set_column('D:E', 15)  # Dates (Center)
        worksheet.set_column('F:G', 25)  # Seller/Buyer (Center)
        worksheet.set_column('H:H', 20)  # Bank (Center)
        worksheet.set_column('I:I', 40)  # Description (Left)
        worksheet.set_column('J:M', 12)  # Numbers (Center)
        worksheet.set_column('N:N', 15)  # TOTAL (Center)
        worksheet.set_column('O:O', 8)   # Currency
        worksheet.set_column('P:P', 30)  # Summary (Left)
        
        current_row = 1
        
        for invoice in invoices:
            # --- WRITE PARENT ROW (INVOICE SUMMARY) ---
            
            worksheet.write(current_row, 0, "INVOICE", parent_center)
            worksheet.write(current_row, 1, invoice.get('Filename', ''), parent_left) 
            worksheet.write_string(current_row, 2, str(invoice.get('Invoice_ID', '')), parent_center) 
            worksheet.write(current_row, 3, invoice.get('Date_Issued', ''), parent_center)
            worksheet.write(current_row, 4, invoice.get('Due_Date', ''), parent_center)
            worksheet.write(current_row, 5, invoice.get('Seller_Name', ''), parent_center)
            
            # FIX: Use clean buyer name
            worksheet.write(current_row, 6, invoice.get('Buyer_Name_Only', ''), parent_center)
            
            worksheet.write(current_row, 7, invoice.get('Bank_IBAN', ''), parent_center)
            
            # Merged visual separator for Item columns in Parent Row
            worksheet.write(current_row, 8, "— Invoice Items Below —", parent_center)
            worksheet.write(current_row, 9, "", parent_center)
            worksheet.write(current_row, 10, "", parent_center)
            worksheet.write(current_row, 11, "", parent_center)
            
            # Financials (Appear ONCE here)
            worksheet.write(current_row, 12, invoice.get('Tax_Amount', 0), parent_money)
            worksheet.write(current_row, 13, invoice.get('Total_Amount', 0), parent_money)
            worksheet.write(current_row, 14, invoice.get('Currency', ''), parent_center)
            worksheet.write(current_row, 15, invoice.get('General_Summary', ''), parent_left) 
            
            current_row += 1
            
            # --- WRITE CHILD ROWS (LINE ITEMS) ---
            items = invoice.get('Line_Items', [])
            if items:
                for item in items:
                    # 'level': 1 makes it a child. 'hidden': True makes it collapsed by default.
                    worksheet.set_row(current_row, None, None, {'level': 1, 'hidden': True})
                    
                    worksheet.write(current_row, 0, "Item", child_center)
                    worksheet.write(current_row, 1, "", child_left) 
                    worksheet.write(current_row, 2, "", child_center) 
                    worksheet.write(current_row, 3, "", child_center) 
                    worksheet.write(current_row, 4, "", child_center) 
                    worksheet.write(current_row, 5, "", child_center) 
                    worksheet.write(current_row, 6, "", child_center) 
                    worksheet.write(current_row, 7, "", child_center) 
                    
                    # Real Item Data
                    worksheet.write(current_row, 8, item.get('Description', ''), child_left)
                    worksheet.write(current_row, 9, item.get('Quantity', ''), child_center)
                    worksheet.write(current_row, 10, item.get('Unit_Price', ''), child_money)
                    worksheet.write(current_row, 11, item.get('Line_Total', ''), child_money)
                    
                    # Empty Totals/Summary in Child Rows
                    worksheet.write(current_row, 12, "", child_money)
                    worksheet.write(current_row, 13, "", child_money)
                    worksheet.write(current_row, 14, "", child_center)
                    worksheet.write(current_row, 15, "", child_left)
                    
                    current_row += 1
            
        # Final Polish: Ignore Errors & Add Filter
        worksheet.ignore_errors({'number_stored_as_text': 'A:Z'})
        worksheet.autofilter(0, 0, current_row, len(headers)-1)
        
        writer.close()
        
    return output.getvalue()

# --- 5. MAIN APP ---

st.title("💎 Enterprise Invoice Digitizer")

# Session State Memory
if "invoice_data_master" not in st.session_state: 
    st.session_state.invoice_data_master = None

if not api_key:
    st.warning("👈 Enter API Key")
    st.stop()
    
try:
    client = genai.Client(api_key=api_key)
except:
    st.error("Invalid Key")
    st.stop()

uploaded_files = st.file_uploader("📂 Upload Invoices", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    if st.button("🚀 Process Invoices"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        all_invoices = []
        
        total_steps = len(uploaded_files)
        
        for i, file in enumerate(uploaded_files):
            file.seek(0)
            file_bytes = file.read()
            
            # BATCH PROCESSOR
            reader = PyPDF2.PdfReader(BytesIO(file_bytes))
            # Safe check for empty files
            page_count = len(reader.pages) if reader.pages else 0
            
            if page_count > 20:
                status_text.write(f"⚙️ Splitting large file: {file.name}")
                batches = split_pdf_into_batches(file_bytes)
            else:
                batches = [{"data": file_bytes, "range": "All"}]
                
            for batch in batches:
                if i > 0: time.sleep(1)
                
                # CALL AI
                chunk_data = get_gemini_response(client, model_choice, batch['data'], file.name, batch['range'])
                
                if chunk_data:
                    if isinstance(chunk_data, dict): chunk_data = [chunk_data]
                    
                    for invoice in chunk_data:
                        invoice['Filename'] = file.name
                        # Safety checks for lists
                        if 'Line_Items' not in invoice or not isinstance(invoice['Line_Items'], list):
                            invoice['Line_Items'] = []
                        all_invoices.append(invoice)
                            
            progress_bar.progress((i + 1) / total_steps)

        if all_invoices:
            st.session_state.invoice_data_master = all_invoices
            status_text.success("✅ Analysis Complete!")
        else:
            status_text.warning("No data found.")

# --- 6. DISPLAY RESULTS ---

if st.session_state.invoice_data_master:
    st.markdown("---")
    st.subheader("📊 Invoice Master-View")
    
    invoices = st.session_state.invoice_data_master
    
    # DOWNLOAD BUTTON
    excel_data = create_flawless_excel(invoices)
    st.download_button(
        "📥 Download Master-Detail Excel",
        data=excel_data,
        file_name="Invoices_Master.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
    
    st.markdown("---")
    
    # UI CARDS
    for inv in invoices:
        label = f"📄 **{inv.get('Seller_Name', 'Unknown')}** | 🆔 {inv.get('Invoice_ID', 'N/A')} | 📅 {inv.get('Date_Issued', 'N/A')}"
        
        with st.expander(label):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total", f"${inv.get('Total_Amount', 0):,.2f}")
            c2.metric("Buyer", inv.get('Buyer_Name_Only', 'N/A'))
            c3.metric("Summary", inv.get('General_Summary', 'N/A'))
            c4.metric("Status", "Processed")
            
            items = inv.get('Line_Items', [])
            if items:
                st.markdown("###### 📦 Items")
                df_items = pd.DataFrame(items)
                cols = ["Description", "Quantity", "Unit_Price", "Line_Total"]
                final_cols = [c for c in cols if c in df_items.columns]
                st.dataframe(df_items[final_cols], use_container_width=True, hide_index=True)