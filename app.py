from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import boto3
import os

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Use secret key from .env (falls back to a default for local dev)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_voting_key")

# Read AWS credentials and config from .env
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
REGION = os.environ.get("AWS_REGION", "ap-south-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

# Configure AWS services using explicit credentials from .env
dynamodb = boto3.resource(
    "dynamodb",
    region_name=REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)
sns_client = boto3.client(
    "sns",
    region_name=REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)


# --- Helper to access tables ---
def get_table(table_name):
    return dynamodb.Table(table_name)


# --- Routes ---
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("vote_page"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # 1. Check if email exists in the authorized "Students" table
        try:
            students_table = get_table("Students")
            response = students_table.get_item(Key={"email": email})
            if "Item" not in response:
                flash(
                    "Signup denied: Your email is not in the student registry.", "error"
                )
                return redirect(url_for("signup"))
        except Exception as e:
            flash(f"Error accessing Students table: {str(e)}", "error")
            return redirect(url_for("signup"))

        # 2. Check if user already registered in "Users" table
        try:
            users_table = get_table("Users")
            response = users_table.get_item(Key={"email": email})
            if "Item" in response:
                flash(
                    "An account with this email already exists. Please log in.", "error"
                )
                return redirect(url_for("login"))
        except Exception as e:
            flash(f"Error accessing Users table: {str(e)}", "error")
            return redirect(url_for("signup"))

        # 3. Hash password and insert into "Users" table
        try:
            hashed_password = generate_password_hash(password)
            users_table.put_item(
                Item={"email": email, "password": hashed_password, "hasVoted": False}
            )
        except Exception as e:
            flash(f"Error creating user: {str(e)}", "error")
            return redirect(url_for("signup"))

        # 4. Subscribe the new user's email to the SNS Topic
        if SNS_TOPIC_ARN:
            try:
                sns_client.subscribe(
                    TopicArn=SNS_TOPIC_ARN, Protocol="email", Endpoint=email
                )
            except Exception as e:
                print(f"SNS Subscription Error: {e}")

        flash(
            "Sign up successful! Please check your email to confirm the subscription, then log in.",
            "success",
        )
        return redirect(url_for("login"))

    return render_template("signup.html")


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
                # Check hashed password
                if check_password_hash(user["password"], password):
                    session["user"] = email
                    flash("Login successful!", "success")
                    return redirect(url_for("vote_page"))

            flash("Invalid email or password.", "error")
        except Exception as e:
            flash(f"Login Error: {str(e)}", "error")

        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/vote", methods=["GET"])
def vote_page():
    if "user" not in session:
        flash("Please log in to view the voting page.", "error")
        return redirect(url_for("login"))

    email = session["user"]

    try:
        users_table = get_table("Users")
        response = users_table.get_item(Key={"email": email})
        user = response.get("Item")

        if not user:
            session.pop("user", None)
            return redirect(url_for("login"))

        has_voted = user.get("hasVoted", False)
    except Exception as e:
        flash(f"Error checking vote status: {str(e)}", "error")
        has_voted = False

    # List of candidates available to vote for
    candidates = ["Alice Smith", "Bob Johnson", "Charlie Davis"]

    return render_template("vote.html", has_voted=has_voted, candidates=candidates)


@app.route("/cast_vote", methods=["POST"], endpoint="vote")
def cast_vote():
    if "user" not in session:
        return redirect(url_for("login"))

    email = session["user"]
    candidate = request.form.get("candidate")

    if not candidate:
        flash("No candidate selected.", "error")
        return redirect(url_for("vote_page"))

    try:
        # 1. Check & Set: Ensure user has not voted yet, gracefully handling DynamoDB condition
        users_table = get_table("Users")
        dynamodb_client = boto3.client("dynamodb", region_name=REGION)

        users_table.update_item(
            Key={"email": email},
            UpdateExpression="SET hasVoted = :v",
            ConditionExpression="hasVoted = :f OR attribute_not_exists(hasVoted)",
            ExpressionAttributeValues={":v": True, ":f": False},
        )
    except dynamodb_client.exceptions.ConditionalCheckFailedException:
        flash("Our records show you have already voted!", "error")
        return redirect(url_for("vote_page"))
    except Exception as e:
        flash(f"Vote record error: {str(e)}", "error")
        return redirect(url_for("vote_page"))

    # 2. Atomic increment of candidate's vote count in "Votes" table
    try:
        votes_table = get_table("Votes")
        votes_table.update_item(
            Key={"candidate": candidate},
            UpdateExpression="ADD votes :inc",
            ExpressionAttributeValues={":inc": 1},
        )
    except Exception as e:
        print(f"Vote increment error: {e}")
        # Not rolling back the User's hasVoted for simplicity, but in production, consider transactions

    # 3. Publish an SNSe mail confirmation asynchronously (or fast sync)
    try:
        if SNS_TOPIC_ARN:
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=f"Hello,\\n\\nThis email confirms that your vote for {candidate} has been successfully recorded in the University Voting System.\\n\\nThank you for participating!",
                Subject="Voting Confirmation - University Elections",
            )
    except Exception as e:
        print(f"SNS Publish Error: {e}")

    flash(
        "Your vote has been cast and recorded successfully! A confirmation email has been dispatched.",
        "success",
    )
    return redirect(url_for("vote_page"))


if __name__ == "__main__":
    # Running locally default on port 5000
    app.run(debug=True, host="0.0.0.0", port=5000)
