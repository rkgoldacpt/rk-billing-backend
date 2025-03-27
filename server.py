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

app = Flask(__name__)
CORS(app)

# ✅ SQLite (For deployment)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///rk_billing.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ✅ Logging Setup
logging.basicConfig(level=logging.INFO)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(20), nullable=False)
    visits = db.relationship('Visit', backref='customer', lazy=True)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    purchased_items = db.Column(db.Text, nullable=True)
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    due_amount = db.Column(db.Float, nullable=False, default=0)

def save_to_excel(filename, data_dict):
    try:
        df = pd.DataFrame(data_dict)
        if os.path.exists(filename):
            existing_df = pd.read_excel(filename)
            df = pd.concat([existing_df, df], ignore_index=True)
        df.to_excel(filename, index=False)
        logging.info(f"Saved to {filename}")
    except Exception as e:
        logging.error(f"Excel write error: {e}")

def save_customer_to_excel(customer):
    save_to_excel("customers.xlsx", {
        "ID": [customer.id],
        "Name": [customer.name],
        "Contact": [customer.contact]
    })

def save_visit_to_excel(visit):
    save_to_excel("visits.xlsx", {
        "Customer ID": [visit.customer_id],
        "Date": [visit.date.strftime('%Y-%m-%d %H:%M:%S')],
        "Purchased Items": [visit.purchased_items],
        "Paid Amount": [visit.paid_amount],
        "Due Amount": [visit.due_amount]
    })

@app.route('/add_customer', methods=['POST'])
def add_customer():
    data = request.json
    if "name" not in data or "contact" not in data:
        return jsonify({"error": "Invalid data"}), 400
    try:
        existing = Customer.query.filter_by(name=data["name"], contact=data["contact"]).first()
        if existing:
            return jsonify({"message": "Customer already exists!", "id": existing.id})
        customer = Customer(name=data["name"], contact=data["contact"])
        db.session.add(customer)
        db.session.commit()
        save_customer_to_excel(customer)
        return jsonify({"message": "Customer added", "id": customer.id})
    except Exception as e:
        db.session.rollback()
        logging.error(f"Add customer error: {e}")
        return jsonify({"error": "Add customer failed"}), 500

@app.route('/search_customer')
def search_customer():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify([])
    try:
        customers = Customer.query.filter(Customer.name.like(f"%{query}%")).limit(5).all()
        return jsonify([{"id": c.id, "name": c.name, "contact": c.contact} for c in customers])
    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({"error": "Search failed"}), 500

@app.route('/add_visit', methods=['POST'])
def add_visit():
    data = request.json
    if "customer_id" not in data or "purchased_items" not in data:
        return jsonify({"error": "Invalid data"}), 400
    try:
        visit = Visit(
            customer_id=data["customer_id"],
            purchased_items="\n".join(data["purchased_items"]),
            paid_amount=data.get("paid_amount", 0),
            due_amount=data.get("due_amount", 0),
        )
        db.session.add(visit)
        db.session.commit()
        save_visit_to_excel(visit)
        return jsonify({"message": "Visit recorded"})
    except Exception as e:
        db.session.rollback()
        logging.error(f"Add visit error: {e}")
        return jsonify({"error": "Visit failed"}), 500

@app.route('/get_customer_history/<int:customer_id>')
def get_customer_history(customer_id):
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({"error": "Not found"}), 404
        visits = Visit.query.filter_by(customer_id=customer_id).order_by(Visit.date.desc()).all()
        return jsonify({
            "visits": [
                {
                    "date": v.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "purchased_items": v.purchased_items,
                    "paid_amount": v.paid_amount,
                    "due_amount": v.due_amount,
                } for v in visits
            ]
        })
    except Exception as e:
        logging.error(f"History error: {e}")
        return jsonify({"error": "History fetch failed"}), 500

@app.route('/generate_invoice/<int:customer_id>')
def generate_invoice(customer_id):
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({"error": "Customer not found"}), 404
        visit = Visit.query.filter_by(customer_id=customer_id).order_by(Visit.date.desc()).first()
        if not visit:
            return jsonify({"error": "No visit found"}), 404

        invoice_file = f"invoice_{customer.name}.pdf"
        doc = SimpleDocTemplate(invoice_file, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        elements += [
            Paragraph("<b>RK JEWELLERS</b>", styles["Title"]),
            Paragraph("<b>ESTIMATION BILL</b>", styles["Title"]),
            Paragraph("Address: MAIN ROAD, OLD BAZAR, ACHAMPET, 509375", styles["Normal"]),
            Paragraph("Contact: +91 9440370408 / +91 9490324969", styles["Normal"]),
            Spacer(1, 10),
            Paragraph(f"<b>Customer Name:</b> {customer.name}", styles["Normal"]),
            Paragraph(f"<b>Contact:</b> {customer.contact}", styles["Normal"]),
            Paragraph(f"<b>Date:</b> {visit.date.strftime('%Y-%m-%d')}", styles["Normal"]),
            Spacer(1, 10),
        ]

        table_data = [["Sr. No.", "Item Name", "Gross Wt.", "Wastage %", "Net Wt.", "Gold Rate", "Lab Rate", "Amount"]]

        items = visit.purchased_items.strip().split("\n")
        for i, item in enumerate(items, 1):
            item = item.strip()
            if not item or not item.startswith("Item: "):
                logging.warning(f"Skipped malformed item: {item}")
                continue
            try:
                name = item.split("Item: ")[1].split(" | ")[0]
                gross = item.split("Gross: ")[1].split("g")[0]
                wastage = item.split("Wastage: ")[1].split("%")[0]
                net = item.split("Net: ")[1].split("g")[0]
                gold_rate = item.split("Gold Rate: Rs.")[1].split(" |")[0]
                lab_rate = item.split("Lab Rate: Rs.")[1].split(" |")[0]
                amount = item.split("Amount: Rs.")[1]
                table_data.append([f"#{i}", name, gross, wastage, net, gold_rate, lab_rate, amount])
            except Exception as e:
                logging.error(f"Parse error item {i}: {e}")
                table_data.append([f"#{i}", item, "-", "-", "-", "-", "-", "-"])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), 10),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(f"<b>Paid Amount:</b> Rs.{visit.paid_amount:.2f}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Due Amount:</b> Rs.{visit.due_amount:.2f}", styles["Normal"]))
        elements.append(Spacer(1, 30))
        elements.append(Table([
            ["Customer Signature", "", "Authorized Signature"],
            ["_________________________", "", "_________________________"]
        ], colWidths=[200, 50, 200]))

        doc.build(elements)
        return send_file(invoice_file, as_attachment=True)
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        return jsonify({"error": "Invoice generation failed"}), 500

@app.route('/')
def home():
    return "RK Billing Backend is running!"

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
