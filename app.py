from flask import (
    Flask, render_template, request, redirect,
    session, flash, Response
)
from functools import wraps
import firebase_admin
from firebase_admin import credentials, firestore
import csv
import io

app = Flask(__name__)
app.secret_key = "change-this-to-a-long-random-string-later"

# ============================================
# FIREBASE CONNECTION
# ============================================

cred = credentials.Certificate(
    "warehouse-management-f4342-firebase-adminsdk-fbsvc-cec82a7bc1.json"
)
firebase_admin.initialize_app(cred)
db = firestore.client()


# ============================================
# AUTH DECORATOR
# ============================================

def login_required(f):
    """Redirect to login page if user is not authenticated."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "error")
            return redirect("/")
        return f(*args, **kwargs)
    return wrapper


# ============================================
# AUTH ROUTES
# ============================================

@app.route("/")
def login():
    # If already logged in, skip straight to dashboard
    if "user" in session:
        return redirect("/dashboard")
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    # --- Option A: simple hardcoded admin (replace later) ---
    if username == "admin" and password == "admin123":
        session["user"] = username
        flash("Welcome back, admin!", "success")
        return redirect("/dashboard")

    # --- Option B: check Firestore "users" collection ---
    # users = db.collection("users").where("username", "==", username).stream()
    # for u in users:
    #     if u.to_dict().get("password") == password:
    #         session["user"] = username
    #         flash(f"Welcome back, {username}!", "success")
    #         return redirect("/dashboard")

    flash("Invalid username or password.", "error")
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect("/")


# ============================================
# DASHBOARD
# ============================================

@app.route("/dashboard")
@login_required
def dashboard():
    product_list = db.collection("products").stream()

    total_products = 0
    total_stock = 0
    low_stock = 0
    out_of_stock = 0
    total_value = 0.0

    for product in product_list:
        data = product.to_dict()

        total_products += 1

        quantity = int(data.get("quantity", 0))
        minimum_stock = int(data.get("minimumStock", 5))
        price = float(data.get("price", 0))

        total_stock += quantity
        total_value += price * quantity

        if quantity == 0:
            out_of_stock += 1
        elif quantity <= minimum_stock:
            low_stock += 1

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_stock=total_stock,
        low_stock=low_stock,
        out_of_stock=out_of_stock,
        total_value=round(total_value, 2)
    )


# ============================================
# PRODUCTS
# ============================================

@app.route("/products")
@login_required
def products():
    product_list = db.collection("products").stream()

    products = []
    for product in product_list:
        data = product.to_dict()
        data["id"] = product.id
        products.append(data)

    return render_template("products.html", products=products)


@app.route("/add-product", methods=["POST"])
@login_required
def add_product():
    try:
        product_data = {
            "productName": request.form["productName"],
            "category": request.form["category"],
            "subCategory": request.form["subCategory"],
            "brand": request.form.get("brand", ""),
            "fabricType": request.form.get("fabricType", ""),
            "color": request.form["color"],
            "size": request.form["size"],
            "price": float(request.form["price"]),
            "quantity": int(request.form["quantity"]),
            "rackNumber": request.form["rackNumber"],
            "minimumStock": int(request.form["minimumStock"]),
        }

        # Prevent duplicates (same name + size + color)
        existing = (
            db.collection("products")
            .where("productName", "==", product_data["productName"])
            .where("size", "==", product_data["size"])
            .where("color", "==", product_data["color"])
            .stream()
        )

        if any(existing):
            flash(
                f"'{product_data['productName']}' "
                f"({product_data['size']}, {product_data['color']}) "
                "already exists.",
                "error",
            )
            return redirect("/products")

        db.collection("products").add(product_data)
        flash(f"'{product_data['productName']}' added successfully.", "success")

    except Exception as e:
        flash(f"Error adding product: {e}", "error")

    return redirect("/products")


@app.route("/edit-product/<product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    ref = db.collection("products").document(product_id)

    if request.method == "POST":
        try:
            ref.update({
                "productName": request.form["productName"],
                "category": request.form["category"],
                "subCategory": request.form["subCategory"],
                "brand": request.form.get("brand", ""),
                "fabricType": request.form.get("fabricType", ""),
                "color": request.form["color"],
                "size": request.form["size"],
                "price": float(request.form["price"]),
                "quantity": int(request.form["quantity"]),
                "rackNumber": request.form["rackNumber"],
                "minimumStock": int(request.form["minimumStock"]),
            })
            flash("Product updated successfully.", "success")
            return redirect("/products")

        except Exception as e:
            flash(f"Error updating product: {e}", "error")
            return redirect("/products")

    product = ref.get().to_dict()
    if not product:
        flash("Product not found.", "error")
        return redirect("/products")

    product["id"] = product_id
    return render_template("edit_product.html", product=product)


@app.route("/delete-product/<product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    try:
        db.collection("products").document(product_id).delete()
        flash("Product deleted.", "success")
    except Exception as e:
        flash(f"Error deleting product: {e}", "error")

    return redirect("/products")


# ============================================
# STOCK MANAGEMENT
# ============================================

@app.route("/stock-management")
@login_required
def stock_management():
    product_list = db.collection("products").stream()

    products = []
    for p in product_list:
        data = p.to_dict()
        data["id"] = p.id
        products.append(data)

    # sort: out-of-stock first, then low stock, then rest
    def priority(p):
        qty = int(p.get("quantity", 0))
        mn = int(p.get("minimumStock", 5))
        if qty == 0:
            return 0
        if qty <= mn:
            return 1
        return 2

    products.sort(key=priority)

    return render_template("stock.html", products=products)


@app.route("/update-stock/<product_id>", methods=["POST"])
@login_required
def update_stock(product_id):
    try:
        qty = int(request.form["quantity"])
        action = request.form.get("action", "in")  # "in" or "out"

        if qty <= 0:
            flash("Quantity must be greater than 0.", "error")
            return redirect("/stock-management")

        ref = db.collection("products").document(product_id)
        current = ref.get().to_dict()

        if not current:
            flash("Product not found.", "error")
            return redirect("/stock-management")

        current_qty = int(current.get("quantity", 0))

        if action == "in":
            new_qty = current_qty + qty
            change = qty
        else:
            new_qty = max(0, current_qty - qty)
            change = -min(qty, current_qty)

        ref.update({"quantity": new_qty})

        # log the movement
        db.collection("stock_history").add({
            "productId": product_id,
            "productName": current.get("productName", ""),
            "change": change,
            "newQuantity": new_qty,
            "user": session.get("user", "unknown"),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })

        flash(
            f"{'Added' if action == 'in' else 'Removed'} "
            f"{abs(change)} unit(s). New stock: {new_qty}.",
            "success",
        )

    except Exception as e:
        flash(f"Error updating stock: {e}", "error")

    return redirect("/stock-management")


# ============================================
# SUPPLIERS
# ============================================

@app.route("/suppliers")
@login_required
def suppliers():
    docs = db.collection("suppliers").stream()
    suppliers = [{"id": d.id, **d.to_dict()} for d in docs]
    return render_template("suppliers.html", suppliers=suppliers)


@app.route("/add-supplier", methods=["POST"])
@login_required
def add_supplier():
    try:
        db.collection("suppliers").add({
            "name": request.form["name"],
            "contactPerson": request.form.get("contactPerson", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "address": request.form.get("address", ""),
            "category": request.form.get("category", ""),
        })
        flash(f"Supplier '{request.form['name']}' added.", "success")
    except Exception as e:
        flash(f"Error adding supplier: {e}", "error")

    return redirect("/suppliers")


@app.route("/delete-supplier/<supplier_id>", methods=["POST"])
@login_required
def delete_supplier(supplier_id):
    try:
        db.collection("suppliers").document(supplier_id).delete()
        flash("Supplier deleted.", "success")
    except Exception as e:
        flash(f"Error deleting supplier: {e}", "error")

    return redirect("/suppliers")


# ============================================
# REPORTS
# ============================================

@app.route("/reports")
@login_required
def reports():
    docs = db.collection("products").stream()
    products = [d.to_dict() for d in docs]

    total_value = 0.0
    total_units = 0
    category_summary = {}
    low_stock_items = []

    for p in products:
        price = float(p.get("price", 0))
        qty = int(p.get("quantity", 0))
        mn = int(p.get("minimumStock", 5))
        value = price * qty

        total_value += value
        total_units += qty

        cat = p.get("category", "Uncategorized")
        if cat not in category_summary:
            category_summary[cat] = {"count": 0, "qty": 0, "value": 0.0}
        category_summary[cat]["count"] += 1
        category_summary[cat]["qty"] += qty
        category_summary[cat]["value"] += value

        if qty <= mn:
            low_stock_items.append({
                "productName": p.get("productName", ""),
                "category": cat,
                "quantity": qty,
                "minimumStock": mn,
            })

    return render_template(
        "reports.html",
        total_products=len(products),
        total_value=round(total_value, 2),
        total_units=total_units,
        category_summary=category_summary,
        low_stock_items=low_stock_items,
    )

@app.route("/export-csv")
@login_required
def export_csv():
    docs = db.collection("products").stream()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Product Name", "Category", "Sub Category", "Brand",
        "Fabric", "Color", "Size", "Price", "Quantity",
        "Rack", "Minimum Stock"
    ])

    for d in docs:
        p = d.to_dict()
        writer.writerow([
            p.get("productName", ""),
            p.get("category", ""),
            p.get("subCategory", ""),
            p.get("brand", ""),
            p.get("fabricType", ""),
            p.get("color", ""),
            p.get("size", ""),
            p.get("price", 0),
            p.get("quantity", 0),
            p.get("rackNumber", ""),
            p.get("minimumStock", 5),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=warehouse_inventory.csv"
        },
    )


# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    app.run(debug=True)