import sys, os

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
from app import create_app
from app.models import db, Film
from app.trailers import fetch_trailer_for_film

app = create_app()
with app.app_context():
    films = Film.query.order_by(Film.id).all()
    ok = 0
    for f in films:
        if f.trailer:
            ok += 1
            print(f"[{f.id}] {f.nom} (déjà: {f.trailer})", flush=True)
            continue
        try:
            res = fetch_trailer_for_film(f)
        except Exception as e:
            res = False
            print(f"[{f.id}] {f.nom} -> erreur {e}", flush=True)
        print(f"[{f.id}] {f.nom} -> {'OK ' + f.trailer if res else 'aucune'}", flush=True)
        if res:
            ok += 1
        db.session.expunge(f)
    print(f"\navec bande-annonce: {ok}/{len(films)}", flush=True)