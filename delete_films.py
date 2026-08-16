import sys

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
import os

os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
from app import create_app
from app.models import db, Film, Actor, Rating, Message, BoxFilm, TopFilm
from sqlalchemy import text

app = create_app()
with app.app_context():
    nb_films = Film.query.count()
    nb_actors = Actor.query.count()
    nb_ratings = Rating.query.count()
    nb_msgs = Message.query.count()
    nb_bf = BoxFilm.query.count()
    nb_tf = TopFilm.query.count()

    db.session.execute(text("DELETE FROM box_films"))
    db.session.execute(text("DELETE FROM top_films"))
    db.session.execute(text("DELETE FROM notations"))
    db.session.execute(text("DELETE FROM messages"))
    db.session.execute(text("DELETE FROM acteurs"))
    db.session.execute(text("DELETE FROM films"))
    db.session.commit()

    print(f"supprimés: films={nb_films}, acteurs={nb_actors}, notations={nb_ratings}, "
          f"messages={nb_msgs}, box_films={nb_bf}, top_films={nb_tf}")
    print(f"restant: films={Film.query.count()}, boxs={__import__('app.models', fromlist=['Box']).Box.query.count()}")
