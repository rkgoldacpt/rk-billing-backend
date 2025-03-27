from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import os
import pandas as pd
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import logging
import json  # Import the json module

app = Flask(__name__)
CORS(app)

# ✅ PostgreSQL connection (Recommended for Production)
# app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://rk_billing_db_user:E6zwWbPM5Z4wvfIex46USfPpYxTh9yE2@dpg-cvhqcq52ng1s739u2jng-a/rk_billing_db"

# ✅ SQLite connection (For simpler setup/testing)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///rk_billing.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ✅ Logging Setup
logging.basicConfig(level=logging.INFO)  # Or logging.DEBUG for more detail

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(20), nullable=False)
    visits = db.relationship('Visit', backref='customer', lazy=True)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    purchased_items = db.Column(db.Text, nullable=True)  # Store as text, will contain \n separated items
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    due_amount = db.Column(db.Float, nullable=False, default=0)

def save_to_excel(filename, data_dict):
    """Saves data to an Excel file."""
    try:
        df = pd.DataFrame(data_dict)
        if os.path.exists(filename):
            existing_df = pd.read_excel(filename)
            df = pd.concat([existing_df, df], ignore_index=True)
        df.to_excel(filename, index=False)
        logging.info(f"Data saved to Excel file: {filename}")
    except Exception as e:
        logging.error(f"Error saving to Excel file: {filename} - {e}")

def save_customer_to_excel(customer):
    """Saves customer data to Excel."""
    save_to_excel("customers.xlsx", {
        "ID": [customer.id],
        "Name": [customer.name],
        "Contact": [customer.contact]
    })

def save_visit_to_excel(visit):
    """Saves visit data to Excel."""
    save_to_excel("visits.xlsx", {
        "Customer ID": [visit.customer_id],
        "Date": [visit.date.strftime('%Y-%m-%d %H:%M:%S')],
        "Purchased Items": [visit.purchased_items],
        "Paid Amount": [visit.paid_amount],
        "Due Amount": [visit.due_amount]
    })

@app.route('/add_customer', methods=['POST'])
def add_customer():
    """Adds a new customer to the database."""
    data = request.json
    if "name" not in data or "contact" not in data:
        return jsonify({"error": "Invalid data, name and contact required"}), 400

    try:
        existing_customer = Customer.query.filter_by(name=data['name'], contact=data['contact']).first()
        if existing_customer:
            return jsonify({"message": "Customer already exists!", "id": existing_customer.id})

        customer = Customer(name=data['name'], contact=data['contact'])
        db.session.add(customer)
        db.session.commit()
        save_customer_to_excel(customer)

        logging.info(f"Customer added: {customer.name} (ID: {customer.id})")
        return jsonify({"message": "Customer added successfully!", "id": customer.id})
    except Exception as e:
        db.session.rollback()  # Rollback in case of error
        logging.error(f"Error adding customer: {e}")
        return jsonify({"error": "Error adding customer"}), 500

@app.route('/search_customer', methods=['GET'])
def search_customer():
    """Searches for customers based on a query."""
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify([])

    try:
        customers = Customer.query.filter(Customer.name.like(f"%{query}%")).limit(5).all()
        return jsonify([{"id": c.id, "name": c.name, "contact": c.contact} for c in customers])
    except Exception as e:
        logging.error(f"Error searching customers: {e}")
        return jsonify({"error": "Error searching customers"}), 500

@app.route('/add_visit', methods=['POST'])
def add_visit():
    """Adds a new visit record to the database."""
    data = request.json
    if "customer_id" not in data or "purchased_items" not in data:
        return jsonify({"error": "Invalid data, customer_id and purchased_items required"}), 400

    try:
        # ✅  Corrected: Use newline as separator
        purchased_items = "\n".join(data['purchased_items'])

        visit = Visit(
            customer_id=data['customer_id'],
            purchased_items=purchased_items,
            paid_amount=data.get("paid_amount", 0),
            due_amount=data.get("due_amount", 0)
        )
        db.session.add(visit)
        db.session.commit()
        save_visit_to_excel(visit)

        logging.info(f"Visit added for customer ID: {data['customer_id']}")
        return jsonify({"message": "Visit recorded successfully!"})
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding visit: {e}")
        return jsonify({"error": "Error recording visit"}), 500

@app.route('/get_customer_history/<int:customer_id>', methods=['GET'])
def get_customer_history(customer_id):
    """Retrieves the visit history for a given customer."""
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        visits = Visit.query.filter_by(customer_id=customer_id).order_by(Visit.date.desc()).all()
        return jsonify({
            "visits": [
                {
                    "date": v.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "purchased_items": v.purchased_items,
                    "paid_amount": v.paid_amount,
                    "due_amount": v.due_amount
                } for v in visits
            ]
        })
    except Exception as e:
        logging.error(f"Error getting customer history for ID {customer_id}: {e}")
        return jsonify({"error": "Error retrieving customer history"}), 500

@app.route('/generate_invoice/<int:customer_id>', methods=['GET'])
def generate_invoice(customer_id):
    """Generates an invoice for a customer's visit."""
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        visit = Visit.query.filter_by(customer_id=customer_id).order_by(Visit.date.desc()).first()
        if not visit:
            return jsonify({"error": "No purchases found"}), 404

        invoice_file = f"invoice_{customer.name}.pdf"
        doc = SimpleDocTemplate(invoice_file, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph("<b>RK JEWELLERS</b>", styles["Title"]))
        elements.append(Paragraph("<b>ESTIMATION BILL</b>", styles["Title"]))
        elements.append(Paragraph("Address: MAIN ROAD, OLD BAZAR, ACHAMPET, 509375", styles["Normal"]))
        elements.append(Paragraph("Contact: +91 9440370408", styles["Normal"]))
        elements.append(Paragraph("         +91 9490324969", styles["Normal"]))
        elements.append(Spacer(1, 10))

        elements.append(Paragraph(f"<b>Customer Name:</b> {customer.name}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Contact:</b> {customer.contact}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Date:</b> {visit.date.strftime('%Y-%m-%d')}", styles["Normal"]))
        elements.append(Spacer(1, 10))

        table_data = [["Sr. No.", "Item Name", "Gross Wt. (g)", "Wastage (%)", "Net Wt. (g)", "Gold Rate (Rs./g)", "Lab Rate (Rs.)", "Amount (Rs.)"]]

        if visit.purchased_items:
            items = visit.purchased_items.split("\n")
            for i, item in enumerate(items, 1):
                item = item.strip()
                if not item or not item.startswith("Item: "):
                    logging.warning(f"Skipping malformed item: '{item}'")
                    table_data.append([f"#{i}", item, "-", "-", "-", "-", "-", "-"])
                    continue
                try:
                    parts = item.split(" | ")
                    item_name = ""
                    gross_wt = ""
                    wastage = ""
                    net_wt = ""
                    gold_rate = ""
                    lab_rate = ""
                    amount = ""

                    for part in parts:
                        if part.startswith("Item: "):
                            item_name = part.split("Item: ")[1]
                        elif part.startswith("Gross: "):
                            gross_wt = part.split("Gross: ")[1].rstrip("g")
                        elif part.startswith("Wastage: "):
                            wastage = part.split("Wastage: ")[1].rstrip("%")
                        elif part.startswith("Net: "):
                            net_wt = part.split("Net: ")[1].rstrip("g")
                        elif part.startswith("Gold Rate: Rs."):
                            gold_rate = part.split("Gold Rate: Rs.")[1]
                        elif part.startswith("Lab Rate: Rs."):
                            lab_rate = part.split("Lab Rate: Rs.")[1]
                        elif part.startswith("Amount: Rs."):
                            amount = part.split("Amount: Rs.")[1]

                    table_data.append([f"#{i}", item_name.strip(), gross_wt.strip(), wastage.strip(), net_wt.strip(), gold_rate.strip(), lab_rate.strip(), amount.strip()])

                except Exception as e:
                    logging.error(f"Error parsing item #{i}: '{item}' — {e}")
                    table_data.append([f"#{i}", item, "-", "-", "-", "-", "-", "-"])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 10))
        elements.append(Paragraph(f"<b>Paid Amount:</b> Rs.{visit.paid_amount:.2f}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Due Amount:</b> Rs.{visit.due_amount:.2f}", styles["Normal"]))
        elements.append(Spacer(1, 40))

        signature_table = Table([
            ["Customer Signature", "", "Authorized Signature"],
            ["_________________________", "", "_________________________"]
        ], colWidths=[200, 50, 200])
        signature_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), "Helvetica-Bold"),
        ]))
        elements.append(signature_table)

        doc.build(elements)
        logging.info(f"Invoice generated for customer ID: {customer_id}")
        return send_file(invoice_file, as_attachment=True)

    except Exception as e:
        logging.error(f"Error generating invoice for customer ID {customer_id}: {e}")
        return jsonify({"error": "Error generating invoice"}), 500

@app.route('/')
def home():
    """Simple home route to check if the backend is running."""
    return "RK Billing Backend is running!"

# ✅ Render fix: create tables + dynamic port
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)