📱 QuickChat CRM

QuickChat CRM is a lightweight contact management and messaging workflow tool designed to streamline WhatsApp-based communication through structured batch processing and prefilled message generation.

It provides a simple interface for uploading contact lists, cleaning data, organizing messaging batches, and launching WhatsApp chats efficiently.

⚙️ Key Features
📂 Contact Management
Upload contacts via .csv or .xlsx files
Automatically reads first column (no headers required)
Cleans and normalizes phone numbers
Removes invalid or empty entries
Prevents duplicate entries using database constraints
🧠 Data Processing
Automatic phone number formatting support
Standardized storage using SQLite database
Persistent contact tracking across sessions
⚡ Batch Messaging Workflow
Batch-based contact selection (e.g. 5, 10, 20, 50)
Sequential processing of pending contacts
Simple action-based workflow:
Open chat
Send message manually
Mark as completed
📲 WhatsApp Integration
Native WhatsApp deep-link support
Prefilled message templates
Direct chat launching via mobile WhatsApp application
📊 Status Tracking
Contact status management:
Pending
Completed
Real-time progress tracking
Completion history stored in database
💬 Message Template Support

Supports dynamic placeholders inside message templates:

{{Number}}

Each contact is dynamically inserted into the message before sending.

🛠️ Tech Stack
Python
Streamlit
SQLite
Pandas
urllib (URL encoding)
📦 Installation
1. Clone repository
git clone https://github.com/your-username/quickchat-crm.git
cd quickchat-crm
2. Install dependencies
pip install -r requirements.txt
3. Run application
streamlit run app.py
📁 Requirements
streamlit
pandas
openpyxl
📱 Workflow Overview
Upload contact file
System processes and stores data
Select batch size
Open WhatsApp chat per contact
Message is automatically prefilled
Send message manually
Mark contact as completed
Repeat until batch is finished
⚠️ Notes
The system does not automate message sending
All messages require manual confirmation in WhatsApp
Designed for structured communication workflows
🔮 Future Enhancements
Multi-campaign management system
Advanced analytics dashboard
Cloud database support
Mobile-first UI improvements
Team collaboration features
