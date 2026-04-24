from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import boto3
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_voting_key")

# ─────────────────────────────────────────────
# CANDIDATES
# ─────────────────────────────────────────────
CANDIDATES = [
    {
        "name": "Hemaditya",
        "photo": "hemaditya.png",
        "agenda": "Academic Excellence & Innovation Hub"
    },
    {
        "name": "Shyam Sunder",
        "photo": "shyam_sunder.png",
        "agenda": "Sports, Library & Transport"
    },
    {
        "name": "Sai Teja",
        "photo": "sai_teja.png",
        "agenda": "Green Campus & Placements"
    },
]

# ─────────────────────────────────────────────
# AWS CONFIG (IAM ROLE BASED — NO KEYS)
# ─────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "ap-south-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

# ✅ No credentials here — uses IAM role automatically
dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns_client = boto3.client("sns", region_name=REGION)

def get_table(name):
    return dynamodb.Table(name)

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("vote_page"))
    return redirect(url_for("login"))

# ───────── SIGNUP ─────────
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        try:
            students_table = get_table("Students")
            if "Item" not in students_table.get_item(Key={"email": email}):
                flash("Email not authorized", "error")
                return redirect(url_for("signup"))

            users_table = get_table("Users")
            if "Item" in users_table.get_item(Key={"email": email}):
                flash("User already exists", "error")
                return redirect(url_for("login"))

            users_table.put_item(
                Item={
                    "email": email,
                    "password": generate_password_hash(password),
                    "hasVoted": False
                }
            )

            if SNS_TOPIC_ARN:
                sns_client.subscribe(
                    TopicArn=SNS_TOPIC_ARN,
                    Protocol="email",
                    Endpoint=email
                )

            flash("Signup successful", "success")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Signup Error: {str(e)}", "error")
            return redirect(url_for("signup"))

    return render_template("signup.html")

# ───────── LOGIN ─────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        try:
            users_table = get_table("Users")
            response = users_table.get_item(Key={"email": email})

            if "Item" in response:
                user = response["Item"]
                if check_password_hash(user["password"], password):
                    session["user"] = email
                    return redirect(url_for("vote_page"))

            flash("Invalid credentials", "error")

        except Exception as e:
            flash(f"Login Error: {str(e)}", "error")

        return redirect(url_for("login"))

    return render_template("login.html")

# ───────── LOGOUT ─────────
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ───────── VOTE PAGE ─────────
@app.route("/vote")
def vote_page():
    if "user" not in session:
        return redirect(url_for("login"))

    email = session["user"]

    users_table = get_table("Users")
    user = users_table.get_item(Key={"email": email}).get("Item")

    has_voted = user.get("hasVoted", False)
    voted_for = user.get("votedFor")

    return render_template(
        "vote.html",
        candidates=CANDIDATES,
        has_voted=has_voted,
        voted_for=voted_for
    )

# ───────── CAST VOTE ─────────
@app.route("/cast_vote", methods=["POST"])
def cast_vote():
    if "user" not in session:
        return redirect(url_for("login"))

    email = session["user"]
    candidate = request.form.get("candidate")

    try:
        users_table = get_table("Users")

        users_table.update_item(
            Key={"email": email},
            UpdateExpression="SET hasVoted = :v, votedFor = :c",
            ConditionExpression="attribute_not_exists(hasVoted) OR hasVoted = :f",
            ExpressionAttributeValues={
                ":v": True,
                ":f": False,
                ":c": candidate
            }
        )

        votes_table = get_table("Votes")
        votes_table.update_item(
            Key={"candidate": candidate},
            UpdateExpression="ADD votes :inc",
            ExpressionAttributeValues={":inc": 1}
        )

        if SNS_TOPIC_ARN:
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=f"You voted for {candidate}",
                Subject="Vote Confirmation"
            )

        flash("Vote recorded!", "success")

    except Exception as e:
        flash(f"Vote Error: {str(e)}", "error")

    return redirect(url_for("vote_page"))

# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
