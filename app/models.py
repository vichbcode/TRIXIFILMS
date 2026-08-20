from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def default_image_dict():
    return {"data": None, "mime": ""}


CATEGORIES = [
    "Action", "Aventure", "Comédie", "Comédie dramatique", "Drame",
    "Horreur", "Thriller", "Science-Fiction", "Fantastique", "Animation",
    "Documentaire", "Policier", "Romance", "Guerre", "Western",
    "Musical", "Biopic", "Historique", "Espionnage", "Catastrophe",
    "Famille", "Fantasy", "Mystère", "Sport", "Érotique"
]

ORIGINES = [
    "Américaine", "Française", "Britannique", "Allemande", "Italienne",
    "Espagnole", "Japonaise", "Coréenne", "Chinoise", "Indienne",
    "Russe", "Australienne", "Canadienne", "Suédoise", "Danoise",
    "Norvégienne", "Belge", "Suisse", "Brésilienne", "Mexicaine",
    "Néerlandaise", "Turque", "Iranienne", "Israélienne", "Polonaise",
    "Autre"
]


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prenom = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False, nullable=False)

    def get_id(self):
        return str(self.id)

    boxs = db.relationship("Box", backref="owner", lazy="select",
                           cascade="all, delete-orphan")
    top_films = db.relationship("TopFilm", backref="user", lazy="select",
                                cascade="all, delete-orphan")


class Film(db.Model):
    __tablename__ = "films"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(200), nullable=False)
    titre_original = Column(String(300), default="")
    langue_originale = Column(String(100), default="")
    resume = Column(Text, default="")
    realisateurs = Column(String(300), default="")
    scenaristes = Column(String(300), default="")
    productions = Column(String(300), default="")
    categorie = Column(String(100), default="")
    origine = Column(String(100), default="")
    image = Column(String(500), default="")
    source = Column(String(20), default="")
    trailer = Column(String(100), default="")

    acteurs = db.relationship("Actor", backref="film", lazy="select",
                              cascade="all, delete-orphan")
    notations = db.relationship("Rating", backref="film", lazy="select",
                                cascade="all, delete-orphan")
    messages = db.relationship("Message", backref="film", lazy="select",
                               cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "nom": self.nom,
            "titre_original": self.titre_original or "",
            "langue_originale": self.langue_originale or "",
            "resume": self.resume or "",
            "realisateurs": self.realisateurs or "",
            "scenaristes": self.scenaristes or "",
            "productions": self.productions or "",
            "categorie": self.categorie or "",
            "origine": self.origine or "",
            "image": self.image or "",
            "source": self.source or "",
            "trailer": self.trailer or "",
        }


class Actor(db.Model):
    __tablename__ = "acteurs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=False)
    nom = Column(String(120), nullable=False)
    image = Column(String(500), default="")
    role = Column(String(100), default="Acteur")


class Rating(db.Model):
    __tablename__ = "notations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=True)
    imdb_id = Column(String(20), default="", index=True)
    prenom = Column(String(100), nullable=False)
    note = Column(Float, nullable=False)


class Message(db.Model):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=True)
    imdb_id = Column(String(20), default="", index=True)
    prenom = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(String(20), default="")


class HiddenFilm(db.Model):
    __tablename__ = "hidden_films"

    id = Column(Integer, primary_key=True, autoincrement=True)
    imdb_id = Column(String(20), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Box(db.Model):
    __tablename__ = "boxs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(200), nullable=False)
    description = Column(Text, default="")
    is_public = Column(Boolean, default=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    films = db.relationship("BoxFilm", backref="box", lazy="select",
                            cascade="all, delete-orphan",
                            order_by="BoxFilm.position")


class BoxFilm(db.Model):
    __tablename__ = "box_films"

    id = Column(Integer, primary_key=True, autoincrement=True)
    box_id = Column(Integer, ForeignKey("boxs.id", ondelete="CASCADE"), nullable=False)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=True)
    imdb_id = Column(String(20), default="", index=True)
    nom = Column(String(200), default="")
    image = Column(String(500), default="")
    position = Column(Integer, default=0)
    added_at = Column(DateTime, default=datetime.utcnow)

    film = db.relationship("Film", lazy="select")


class TopFilm(db.Model):
    __tablename__ = "top_films"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=True)
    imdb_id = Column(String(20), default="", index=True)
    nom = Column(String(200), default="")
    image = Column(String(500), default="")
    position = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    film = db.relationship("Film", lazy="select")
