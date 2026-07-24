from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, LargeBinary
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def default_image_dict():
    return {"data": None, "mime": ""}


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prenom = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)

    def get_id(self):
        return str(self.id)


class Film(db.Model):
    __tablename__ = "films"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(200), nullable=False)
    resume = Column(Text, default="")
    realisateurs = Column(String(300), default="")
    scenaristes = Column(String(300), default="")
    productions = Column(String(300), default="")
    image = Column(String(500), default="")
    image_data = Column(LargeBinary, nullable=True)
    image_mime = Column(String(50), default="")
    source = Column(String(20), default="")

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
            "resume": self.resume or "",
            "realisateurs": self.realisateurs or "",
            "scenaristes": self.scenaristes or "",
            "productions": self.productions or "",
            "image": self.image or "",
            "source": self.source or "",
        }


class Actor(db.Model):
    __tablename__ = "acteurs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=False)
    nom = Column(String(120), nullable=False)
    image = Column(String(500), default="")
    image_data = Column(LargeBinary, nullable=True)
    image_mime = Column(String(50), default="")
    role = Column(String(100), default="Acteur")


class Rating(db.Model):
    __tablename__ = "notations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=False)
    prenom = Column(String(100), nullable=False)
    note = Column(Float, nullable=False)


class Message(db.Model):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=False)
    prenom = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(String(20), default="")
