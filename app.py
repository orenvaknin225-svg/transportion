import os
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-now")

database_url = os.getenv("DATABASE_URL") 
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///fleet.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(50), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    license_due = db.Column(db.Date, nullable=True)
    current_km = db.Column(db.Integer, default=0)
    last_service_date = db.Column(db.Date, nullable=True)
    last_service_km = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)


class VehicleService(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    action_date = db.Column(db.Date, nullable=False)
    km = db.Column(db.Integer, nullable=True)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=True)
    cost = db.Column(db.Float, default=0)
    notes = db.Column(db.Text, nullable=True)

    vehicle = db.relationship("Vehicle", backref="services")


class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    personal_number = db.Column(db.String(100), unique=True, nullable=False)
    license_number = db.Column(db.String(100), nullable=False)
    license_type = db.Column(db.String(100), nullable=False)
    license_expiry = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)


def is_admin():
    return session.get("admin") is True


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def expiry_class(expiry_date):
    if not expiry_date:
        return ""
    today = date.today()
    days_left = (expiry_date - today).days
    if days_left < 0:
        return "expired"
    if days_left <= 30:
        return "soon"
    return "ok"


@app.context_processor
def inject_helpers():
    return dict(expiry_class=expiry_class)


@app.route("/")
def home():
    if is_admin():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "12345678")

    if username == admin_username and password == admin_password:
        session["admin"] = True
        return redirect(url_for("dashboard"))

    flash("שם משתמש או סיסמה לא נכונים")
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    if not is_admin():
        return redirect(url_for("home"))

    vehicles_count = Vehicle.query.count()
    drivers_count = Driver.query.count()
    return render_template("dashboard.html", vehicles_count=vehicles_count, drivers_count=drivers_count)


@app.route("/vehicles")
def vehicles():
    if not is_admin():
        return redirect(url_for("home"))

    q = request.args.get("q", "").strip()
    query = Vehicle.query

    if q:
        query = query.filter(
            db.or_(
                Vehicle.plate_number.ilike(f"%{q}%"),
                Vehicle.vehicle_type.ilike(f"%{q}%"),
                Vehicle.category.ilike(f"%{q}%")
            )
        )

    vehicles_list = query.order_by(Vehicle.plate_number.asc()).all()
    return render_template("vehicles.html", vehicles=vehicles_list, q=q)


@app.route("/vehicles/new", methods=["GET", "POST"]) 
def new_vehicle():
    if not is_admin():
        return redirect(url_for("home"))

    if request.method == "POST":
        plate_number = request.form.get("plate_number", "").strip()
        vehicle_type = request.form.get("vehicle_type", "").strip()
        category = request.form.get("category", "").strip()

        if not plate_number or not vehicle_type or not category:
            flash("חובה למלא מספר רכב, סוג וקטגוריה")
            return redirect(url_for("new_vehicle"))

        vehicle = Vehicle(
            plate_number=plate_number,
            vehicle_type=vehicle_type,
            category=category,
            license_due=parse_date(request.form.get("license_due")),
            current_km=int(request.form.get("current_km") or 0),
            last_service_date=parse_date(request.form.get("last_service_date")),
            last_service_km=int(request.form.get("last_service_km") or 0) if request.form.get("last_service_km") else None,
            notes=request.form.get("notes", "").strip()
        )

        db.session.add(vehicle)
        db.session.commit()
        flash("הרכב נוסף בהצלחה")
        return redirect(url_for("vehicles"))

    return render_template("new_vehicle.html")


@app.route("/vehicles/<int:vehicle_id>", methods=["GET", "POST"]) def vehicle_detail(vehicle_id):
    if not is_admin():
        return redirect(url_for("home"))

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if request.method == "POST":
        service = VehicleService(
            vehicle_id=vehicle.id,
            action_type=request.form.get("action_type", "טיפול"),
            action_date=parse_date(request.form.get("action_date")) or date.today(),
            km=int(request.form.get("km") or 0) if request.form.get("km") else None,
            description=request.form.get("description", "").strip(),
            location=request.form.get("location", "").strip(),
            cost=float(request.form.get("cost") or 0),
            notes=request.form.get("notes", "").strip()
        )

        db.session.add(service)

        vehicle.last_service_date = service.action_date
        if service.km:
            vehicle.last_service_km = service.km
            vehicle.current_km = max(vehicle.current_km or 0, service.km)

        db.session.commit()
        flash("הטיפול / תיקון נוסף בהצלחה")
        return redirect(url_for("vehicle_detail", vehicle_id=vehicle.id))

    services = VehicleService.query.filter_by(vehicle_id=vehicle.id).order_by(VehicleService.action_date.desc()).all()
    total_cost = sum(s.cost or 0 for s in services)
    return render_template("vehicle_detail.html", vehicle=vehicle, services=services, total_cost=total_cost)


@app.route("/drivers")
def drivers():
    if not is_admin():
        return redirect(url_for("home"))

    q = request.args.get("q", "").strip()
    query = Driver.query

    if q:
        query = query.filter(
            db.or_(
                Driver.name.ilike(f"%{q}%"),
                Driver.personal_number.ilike(f"%{q}%"),
                Driver.license_number.ilike(f"%{q}%")
            )
        )

    drivers_list = query.order_by(Driver.name.asc()).all()
    return render_template("drivers.html", drivers=drivers_list, q=q)


@app.route("/drivers/new", methods=["GET", "POST"]) def new_driver():
    if not is_admin():
        return redirect(url_for("home"))

    if request.method == "POST":
        driver = Driver(
            name=request.form.get("name", "").strip(),
            personal_number=request.form.get("personal_number", "").strip(),
            license_number=request.form.get("license_number", "").strip(),
            license_type=request.form.get("license_type", "").strip(),
            license_expiry=parse_date(request.form.get("license_expiry")),
            notes=request.form.get("notes", "").strip()
        )

        if not driver.name or not driver.personal_number:
            flash("חובה למלא שם ומספר אישי")
            return redirect(url_for("new_driver"))

        db.session.add(driver)
        db.session.commit()
        flash("הנהג נוסף בהצלחה")
        return redirect(url_for("drivers"))

    return render_template("new_driver.html")


@app.route("/drivers/<int:driver_id>")
def driver_detail(driver_id):
    if not is_admin():
        return redirect(url_for("home"))

    driver = Driver.query.get_or_404(driver_id)
    return render_template("driver_detail.html", driver=driver)


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
