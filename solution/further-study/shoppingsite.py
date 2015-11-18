"""Ubermelon shopping application Flask server.

Provides web interface for browsing melons, seeing detail about a melon, and
put melons in a shopping cart.

Authors: Joel Burton, Christian Fernandez, Meggie Mahnken.
"""


from flask import Flask, render_template, redirect, flash, session, request, url_for, jsonify
import jinja2

import melons, customers
import time
import random

# import redis & celery
from redis import Redis
from celery import Celery


app = Flask(__name__)
# connect celery to redis
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379'

# setup celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

app.secret_key = 'this-should-be-something-unguessable'

# Normally, if you refer to an undefined variable in a Jinja template,
# Jinja silently ignores this. This makes debugging difficult, so we'll
# set an attribute of the Jinja environment that says to make this an
# error.

app.jinja_env.undefined = jinja2.StrictUndefined

@celery.task(bind=True)
def long_task(self):
    """Background task that runs a long function with progress reports."""
    verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
    adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
    noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
    message = ''
    total = random.randint(10, 50)
    for i in range(total):
        if not message or random.random() < 0.25:
            message = '{0} {1} {2}...'.format(random.choice(verb),
                                              random.choice(adjective),
                                              random.choice(noun))
        self.update_state(state='PROGRESS',
                          meta={'current': i, 'total': total,
                                'status': message})
        time.sleep(1)
    return {'current': 100, 'total': 100, 'status': 'Task completed!',
            'result': 42}


@app.route('/longtask', methods=['POST'])
def longtask():
    task = long_task.apply_async()
    return jsonify({}), 202, {'Location': url_for('taskstatus',
                                                  task_id=task.id)}

@app.route('/status/<task_id>')
def taskstatus(task_id):
    task = long_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)

@app.route("/")
def index():
    """Return homepage."""

    return render_template("homepage.html")


@app.route("/melons")
def list_melons():
    """Return page showing all the melons ubermelon has to offer"""

    melon_list = melons.get_all()
    return render_template("all_melons.html",
                           melon_list=melon_list)


@app.route("/melon/<int:melon_id>")
def show_melon(melon_id):
    """Return page showing the details of a given melon.

    Show all info about a melon. Also, provide a button to buy that melon.
    """

    melon = melons.get_by_id(melon_id)
    print melon
    return render_template("melon_details.html",
                           display_melon=melon)


@app.route("/cart")
def shopping_cart():
    """Display content of shopping cart."""

    order_total = 0

    # Get the cart (or an empty list if there's no cart yet)
    raw_cart_ids = session.get('cart', [])

    # We'll use this dictionary to keep track of the melon types
    # we have in the cart.
    #
    # Format: id -> {dictionary-of-melon-info}

    cart = {}

    # Loop over the melon IDs in the session cart to build up the
    # `cart` dictionary

    for melon_id in raw_cart_ids:

        if melon_id in cart:
            cart_info = cart[melon_id]

        else:
            melon_type = melons.get_by_id(melon_id)
            cart_info = cart[melon_id] = {
                'common_name': melon_type.common_name,
                'unit_cost': melon_type.price,
                'qty': 0,
                'total_cost': 0,
            }

        # increase quantity, update melon-total cost by cost of this melon
        cart_info['qty'] += 1
        cart_info['total_cost'] += cart_info['unit_cost']

        # increase order total by cost of this melon
        order_total += cart_info['unit_cost']

    # Get the melon-info dictionaries from our cart
    cart = cart.values()

    return render_template("cart.html", cart=cart, order_total=order_total)


@app.route("/add_to_cart/<int:id>")
def add_to_cart(id):
    """Add a melon to cart and redirect to shopping cart page.

    When a melon is added to the cart, redirect browser to the shopping cart
    page and display a confirmation message: 'Successfully added to cart'.
    """

    # Check if we have a cart in the session dictionary and, if not, add one
    if 'cart' in session:
        cart = session['cart']

    else:
        cart = session['cart'] = []

    # Add melon to cart
    cart.append(id)

    # Show user success message on next page load
    flash("Successfully added to cart.")

    # Redirect to shopping cart page
    return redirect("/cart")


@app.route("/login", methods=["GET"])
def show_login():
    """Show login form."""

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def process_login():
    """Log user into site.

    Find the user's login credentials located in the 'request.form'
    dictionary, look up the user, and store them in the session.
    """

    email = request.form.get('email')
    password = request.form.get('password')

    user = customers.get_by_email(email)

    if not user:
        flash("No such email address.")
        return redirect('/login')

    if user.password != password:
        flash("Incorrect password.")
        return redirect("/login")

    session["logged_in_customer_email"] = user.email
    flash("Logged in.")
    return redirect("/melons")


@app.route("/logout")
def process_logout():
    """Log user out."""

    del session["logged_in_customer_email"]
    flash("Logged out.")
    return redirect("/melons")\


@app.route("/checkout")
def checkout():
    """Checkout customer, process payment, and ship melons."""

    # For now, we'll just provide a warning. Completing this is beyond the
    # scope of this exercise.

    flash("Sorry! Checkout will be implemented in a future version.")
    return redirect("/melons")


if __name__ == "__main__":
    app.run(debug=True)
