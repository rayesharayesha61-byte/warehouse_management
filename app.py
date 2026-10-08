from flask import (
    Flask, render_template, request, redirect,
    session, flash, Response
)
from functools import wraps
import firebase_admin
from firebase_admin import credentials, firestore
import csv
import io
import os
import json

app = Flask(__name__)

# ============================================
# FLASK SECRET KEY
# ============================================

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-to-a-long-random-string"
)


# ============================================
# FIREBASE CONNECTION
# ============================================

def initialize_firebase():
    """
    Initialize Firebase using Render environment variable.

    Local development:
        Uses the Firebase JSON file if available.

    Render:
        Uses FIREBASE_CREDENTIALS environment variable.
    """

    if firebase_admin._apps:
        return firestore.client()

    # ----------------------------------------
    # Render / Production
    # ----------------------------------------
    firebase_credentials = os.environ.get("FIREBASE_CREDENTIALS")

    if firebase_credentials:
        try:
            credentials_dict = json.loads(firebase_credentials)

            cred = credentials.Certificate(credentials_dict)

            firebase_admin.initialize_app(cred)

            return firestore.client()

        except Exception as e:
            print("Firebase environment variable error:", e)
            raise

    # ----------------------------------------
    # Local development
    # ----------------------------------------
    local_json_file = (
        "warehouse-management-f4342"
        "-firebase-adminsdk-fbsvc-cec82a7bc1.json"
    )

    if os.path.exists(local_json_file):
        cred = credentials.Certificate(local_json_file)

        firebase_admin.initialize_app(cred)

        return firestore.client()

    raise RuntimeError(
        "Firebase credentials not found. "
        "Set FIREBASE_CREDENTIALS in Render Environment Variables."
    )


db = initialize_firebase()


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

    if "user" in session:
        return redirect("/dashboard")

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_user():

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    # ----------------------------------------
    # Admin Login
    # ----------------------------------------

    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        "admin"
    )

    admin_password = os.environ.get(
        "ADMIN_PASSWORD",
        "admin123"
    )

    if username == admin_username and password == admin_password:

        session["user"] = username

        flash("Welcome back, admin!", "success")

        return redirect("/dashboard")

    # ----------------------------------------
    # Firestore User Login
    # ----------------------------------------

    # users = (
    #     db.collection("users")
    #     .where("username", "==", username)
    #     .stream()
    # )

    # for user in users:
    #     user_data = user.to_dict()

    #     if user_data.get("password") == password:
    #         session["user"] = username
    #         flash(
    #             f"Welcome back, {username}!",
    #             "success"
    #         )
    #         return redirect("/dashboard")

    flash("Invalid username or password.", "error")

    return redirect("/")


@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

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

        quantity = int(
            data.get("quantity", 0)
        )

        minimum_stock = int(
            data.get("minimumStock", 5)
        )

        price = float(
            data.get("price", 0)
        )

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

    product_list = db.collection(
        "products"
    ).stream()

    products = []

    for product in product_list:

        data = product.to_dict()

        data["id"] = product.id

        products.append(data)

    return render_template(
        "products.html",
        products=products
    )


@app.route("/add-product", methods=["POST"])
@login_required
def add_product():

    try:

        product_data = {
            "productName": request.form["productName"],
            "category": request.form["category"],
            "subCategory": request.form["subCategory"],
            "brand": request.form.get("brand", ""),
            "fabricType": request.form.get(
                "fabricType",
                ""
            ),
            "color": request.form["color"],
            "size": request.form["size"],
            "price": float(
                request.form["price"]
            ),
            "quantity": int(
                request.form["quantity"]
            ),
            "rackNumber": request.form[
                "rackNumber"
            ],
            "minimumStock": int(
                request.form["minimumStock"]
            ),
        }

        # ------------------------------------
        # Duplicate Check
        # ------------------------------------

        existing = (
            db.collection("products")
            .where(
                "productName",
                "==",
                product_data["productName"]
            )
            .where(
                "size",
                "==",
                product_data["size"]
            )
            .where(
                "color",
                "==",
                product_data["color"]
            )
            .stream()
        )

        if any(existing):

            flash(
                f"'{product_data['productName']}' "
                f"({product_data['size']}, "
                f"{product_data['color']}) "
                "already exists.",
                "error"
            )

            return redirect("/products")

        # ------------------------------------
        # Add Product
        # ------------------------------------

        db.collection(
            "products"
        ).add(product_data)

        flash(
            f"'{product_data['productName']}' "
            "added successfully.",
            "success"
        )

    except Exception as e:

        flash(
            f"Error adding product: {e}",
            "error"
        )

    return redirect("/products")


@app.route(
    "/edit-product/<product_id>",
    methods=["GET", "POST"]
)
@login_required
def edit_product(product_id):

    ref = db.collection(
        "products"
    ).document(product_id)

    if request.method == "POST":

        try:

            ref.update({
                "productName": request.form[
                    "productName"
                ],
                "category": request.form[
                    "category"
                ],
                "subCategory": request.form[
                    "subCategory"
                ],
                "brand": request.form.get(
                    "brand",
                    ""
                ),
                "fabricType": request.form.get(
                    "fabricType",
                    ""
                ),
                "color": request.form[
                    "color"
                ],
                "size": request.form[
                    "size"
                ],
                "price": float(
                    request.form["price"]
                ),
                "quantity": int(
                    request.form["quantity"]
                ),
                "rackNumber": request.form[
                    "rackNumber"
                ],
                "minimumStock": int(
                    request.form["minimumStock"]
                ),
            })

            flash(
                "Product updated successfully.",
                "success"
            )

            return redirect("/products")

        except Exception as e:

            flash(
                f"Error updating product: {e}",
                "error"
            )

            return redirect("/products")

    product_snapshot = ref.get()

    if not product_snapshot.exists:

        flash(
            "Product not found.",
            "error"
        )

        return redirect("/products")

    product = product_snapshot.to_dict()

    product["id"] = product_id

    return render_template(
        "edit_product.html",
        product=product
    )


@app.route(
    "/delete-product/<product_id>",
    methods=["POST"]
)
@login_required
def delete_product(product_id):

    try:

        db.collection(
            "products"
        ).document(product_id).delete()

        flash(
            "Product deleted.",
            "success"
        )

    except Exception as e:

        flash(
            f"Error deleting product: {e}",
            "error"
        )

    return redirect("/products")


# ============================================
# STOCK MANAGEMENT
# ============================================

@app.route("/stock-management")
@login_required
def stock_management():

    product_list = db.collection(
        "products"
    ).stream()

    products = []

    for product in product_list:

        data = product.to_dict()

        data["id"] = product.id

        products.append(data)

    # ----------------------------------------
    # Stock Priority
    # ----------------------------------------

    def priority(product):

        quantity = int(
            product.get("quantity", 0)
        )

        minimum_stock = int(
            product.get("minimumStock", 5)
        )

        if quantity == 0:
            return 0

        if quantity <= minimum_stock:
            return 1

        return 2

    products.sort(key=priority)

    return render_template(
        "stock.html",
        products=products
    )


@app.route(
    "/update-stock/<product_id>",
    methods=["POST"]
)
@login_required
def update_stock(product_id):

    try:

        quantity = int(
            request.form["quantity"]
        )

        action = request.form.get(
            "action",
            "in"
        )

        if quantity <= 0:

            flash(
                "Quantity must be greater than 0.",
                "error"
            )

            return redirect(
                "/stock-management"
            )

        ref = db.collection(
            "products"
        ).document(product_id)

        current_snapshot = ref.get()

        if not current_snapshot.exists:

            flash(
                "Product not found.",
                "error"
            )

            return redirect(
                "/stock-management"
            )

        current = current_snapshot.to_dict()

        current_quantity = int(
            current.get("quantity", 0)
        )

        # ------------------------------------
        # Stock In
        # ------------------------------------

        if action == "in":

            new_quantity = (
                current_quantity + quantity
            )

            change = quantity

        # ------------------------------------
        # Stock Out
        # ------------------------------------

        else:

            new_quantity = max(
                0,
                current_quantity - quantity
            )

            change = -min(
                quantity,
                current_quantity
            )

        # ------------------------------------
        # Update Product
        # ------------------------------------

        ref.update({
            "quantity": new_quantity
        })

        # ------------------------------------
        # Stock History
        # ------------------------------------

        db.collection(
            "stock_history"
        ).add({
            "productId": product_id,
            "productName": current.get(
                "productName",
                ""
            ),
            "change": change,
            "newQuantity": new_quantity,
            "user": session.get(
                "user",
                "unknown"
            ),
            "timestamp":
                firestore.SERVER_TIMESTAMP,
        })

        flash(
            f"{'Added' if action == 'in' else 'Removed'} "
            f"{abs(change)} unit(s). "
            f"New stock: {new_quantity}.",
            "success"
        )

    except Exception as e:

        flash(
            f"Error updating stock: {e}",
            "error"
        )

    return redirect(
        "/stock-management"
    )


# ============================================
# SUPPLIERS
# ============================================

@app.route("/suppliers")
@login_required
def suppliers():

    docs = db.collection(
        "suppliers"
    ).stream()

    suppliers = [
        {
            "id": doc.id,
            **doc.to_dict()
        }
        for doc in docs
    ]

    return render_template(
        "suppliers.html",
        suppliers=suppliers
    )


@app.route(
    "/add-supplier",
    methods=["POST"]
)
@login_required
def add_supplier():

    try:

        db.collection(
            "suppliers"
        ).add({
            "name": request.form["name"],
            "contactPerson": request.form.get(
                "contactPerson",
                ""
            ),
            "phone": request.form.get(
                "phone",
                ""
            ),
            "email": request.form.get(
                "email",
                ""
            ),
            "address": request.form.get(
                "address",
                ""
            ),
            "category": request.form.get(
                "category",
                ""
            ),
        })

        flash(
            f"Supplier "
            f"'{request.form['name']}' "
            "added.",
            "success"
        )

    except Exception as e:

        flash(
            f"Error adding supplier: {e}",
            "error"
        )

    return redirect("/suppliers")


@app.route(
    "/delete-supplier/<supplier_id>",
    methods=["POST"]
)
@login_required
def delete_supplier(supplier_id):

    try:

        db.collection(
            "suppliers"
        ).document(supplier_id).delete()

        flash(
            "Supplier deleted.",
            "success"
        )

    except Exception as e:

        flash(
            f"Error deleting supplier: {e}",
            "error"
        )

    return redirect("/suppliers")


# ============================================
# REPORTS
# ============================================

@app.route("/reports")
@login_required
def reports():

    docs = db.collection(
        "products"
    ).stream()

    products = [
        doc.to_dict()
        for doc in docs
    ]

    total_value = 0.0
    total_units = 0

    category_summary = {}

    low_stock_items = []

    for product in products:

        price = float(
            product.get("price", 0)
        )

        quantity = int(
            product.get("quantity", 0)
        )

        minimum_stock = int(
            product.get("minimumStock", 5)
        )

        value = price * quantity

        total_value += value

        total_units += quantity

        category = product.get(
            "category",
            "Uncategorized"
        )

        if category not in category_summary:

            category_summary[category] = {
                "count": 0,
                "qty": 0,
                "value": 0.0
            }

        category_summary[category][
            "count"
        ] += 1

        category_summary[category][
            "qty"
        ] += quantity

        category_summary[category][
            "value"
        ] += value

        if quantity <= minimum_stock:

            low_stock_items.append({
                "productName": product.get(
                    "productName",
                    ""
                ),
                "category": category,
                "quantity": quantity,
                "minimumStock": minimum_stock,
            })

    return render_template(
        "reports.html",
        total_products=len(products),
        total_value=round(
            total_value,
            2
        ),
        total_units=total_units,
        category_summary=category_summary,
        low_stock_items=low_stock_items,
    )


# ============================================
# EXPORT CSV
# ============================================

@app.route("/export-csv")
@login_required
def export_csv():

    docs = db.collection(
        "products"
    ).stream()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Product Name",
        "Category",
        "Sub Category",
        "Brand",
        "Fabric",
        "Color",
        "Size",
        "Price",
        "Quantity",
        "Rack",
        "Minimum Stock"
    ])

    for doc in docs:

        product = doc.to_dict()

        writer.writerow([
            product.get(
                "productName",
                ""
            ),
            product.get(
                "category",
                ""
            ),
            product.get(
                "subCategory",
                ""
            ),
            product.get(
                "brand",
                ""
            ),
            product.get(
                "fabricType",
                ""
            ),
            product.get(
                "color",
                ""
            ),
            product.get(
                "size",
                ""
            ),
            product.get(
                "price",
                0
            ),
            product.get(
                "quantity",
                0
            ),
            product.get(
                "rackNumber",
                ""
            ),
            product.get(
                "minimumStock",
                5
            ),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; "
                "filename="
                "warehouse_inventory.csv"
        },
    )


# ============================================
# HEALTH CHECK
# ============================================

@app.route("/health")
def health():

    return {
        "status": "ok",
        "message": "Warehouse Management System is running"
    }


# ============================================
# RUN
# ============================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )