import os, secrets, re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR=os.path.abspath(os.path.dirname(__file__))
DB_PATH=os.path.join(BASE_DIR,"linkchat.db")
app=Flask(__name__)
app.config["SECRET_KEY"]=os.environ.get("SECRET_KEY","dev-change-this-secret")
app.config["SQLALCHEMY_DATABASE_URI"]=os.environ.get("DATABASE_URL",f"sqlite:///{DB_PATH}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
app.config["PERMANENT_SESSION_LIFETIME"]=timedelta(hours=24)
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"]=app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://","postgresql://",1)
db=SQLAlchemy(app)
socketio=SocketIO(app,cors_allowed_origins="*",async_mode="threading",manage_session=True)

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    username=db.Column(db.String(80),unique=True,nullable=False,index=True)
    password_hash=db.Column(db.String(255),nullable=False)
    bio=db.Column(db.String(300),default="")
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class ChatRoom(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    room_code=db.Column(db.String(32),unique=True,nullable=False,index=True)
    name=db.Column(db.String(120),nullable=False)
    description=db.Column(db.String(300),default="")
    is_private=db.Column(db.Boolean,default=False,nullable=False)
    host_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    host=db.relationship("User",backref="hosted_rooms")

class RoomMember(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    room_id=db.Column(db.Integer,db.ForeignKey("chat_room.id"),nullable=False)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    joined_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    room=db.relationship("ChatRoom",backref="members")
    user=db.relationship("User")
    __table_args__=(db.UniqueConstraint("room_id","user_id",name="uq_room_member"),)

class Message(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    room_id=db.Column(db.Integer,db.ForeignKey("chat_room.id"),nullable=False)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    content=db.Column(db.Text,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)
    room=db.relationship("ChatRoom")
    user=db.relationship("User")

class DirectMessage(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    sender_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    receiver_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    content=db.Column(db.Text,nullable=False)
    is_read=db.Column(db.Boolean,default=False,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    sender=db.relationship("User",foreign_keys=[sender_id])
    receiver=db.relationship("User",foreign_keys=[receiver_id])

def me():
    return db.session.get(User,session.get("user_id")) if session.get("user_id") else None
def guard():
    return None if session.get("user_id") else redirect(url_for("login",next=request.path))
def get_room(code):
    return ChatRoom.query.filter_by(room_code=code).first()
def member(room,uid):
    return RoomMember.query.filter_by(room_id=room.id,user_id=uid).first() is not None
def add_member(room,uid):
    if not member(room,uid):
        db.session.add(RoomMember(room_id=room.id,user_id=uid)); db.session.commit()

@app.context_processor
def ctx(): return {"current_user":me()}

@app.route("/")
def index(): return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/signup",methods=["GET","POST"])
def signup():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method=="POST":
        u=request.form.get("username","").strip(); p=request.form.get("password",""); c=request.form.get("confirm","")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}",u): flash("Username must be 3–30 characters using letters, numbers, _, ., or -.","error")
        elif len(p)<8: flash("Password must contain at least 8 characters.","error")
        elif p!=c: flash("Passwords do not match.","error")
        elif User.query.filter_by(username=u).first(): flash("Username already exists.","error")
        else:
            x=User(username=u,password_hash=generate_password_hash(p)); db.session.add(x); db.session.commit()
            session.clear(); session["user_id"]=x.id; session.permanent=True
            flash("Account created successfully.","success"); return redirect(url_for("dashboard"))
    return render_template("signup.html")

@app.route("/login",methods=["GET","POST"])
def login():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method=="POST":
        u=request.form.get("username","").strip(); p=request.form.get("password",""); x=User.query.filter_by(username=u).first()
        if x and check_password_hash(x.password_hash,p):
            session.clear(); session["user_id"]=x.id; session.permanent=True
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.","error")
    return render_template("login.html")

@app.route("/logout",methods=["GET","POST"])
def logout():
    session.clear(); flash("Logged out.","success"); return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    g=guard()
    if g:return g
    u=me()
    public=ChatRoom.query.filter_by(is_private=False).order_by(ChatRoom.created_at.desc()).all()
    mine=ChatRoom.query.join(RoomMember,RoomMember.room_id==ChatRoom.id).filter(RoomMember.user_id==u.id).order_by(ChatRoom.created_at.desc()).all()
    users=User.query.filter(User.id!=u.id).order_by(User.username).all()
    return render_template("dashboard.html",public_rooms=public,my_rooms=mine,users=users)

@app.route("/profile",methods=["GET","POST"])
def profile():
    g=guard()
    if g:return g
    u=me()
    if request.method=="POST":
        name=request.form.get("username","").strip(); bio=request.form.get("bio","").strip()[:300]
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}",name): flash("Invalid username.","error")
        elif User.query.filter(User.username==name,User.id!=u.id).first(): flash("Username already taken.","error")
        else: u.username=name; u.bio=bio; db.session.commit(); flash("Profile updated.","success")
    return render_template("profile.html",user=u)

@app.route("/create-room",methods=["POST"])
def create_room():
    g=guard()
    if g:return g
    name=request.form.get("name","").strip()[:120]; desc=request.form.get("description","").strip()[:300]
    private=request.form.get("is_private")=="on"
    if not name: flash("Room name is required.","error"); return redirect(url_for("dashboard"))
    code=secrets.token_urlsafe(12).replace("-","").replace("_","")[:16]
    while get_room(code): code=secrets.token_urlsafe(12).replace("-","").replace("_","")[:16]
    r=ChatRoom(room_code=code,name=name,description=desc,is_private=private,host_id=session["user_id"])
    db.session.add(r); db.session.flush(); db.session.add(RoomMember(room_id=r.id,user_id=session["user_id"])); db.session.commit()
    return render_template("room_created.html",room=r,share_url=url_for("join_by_link",room_code=code,_external=True))

@app.route("/join/<room_code>",methods=["GET","POST"])
def join_by_link(room_code):
    r=get_room(room_code)
    if not r:return render_template("not_found.html",message="Invalid or expired chatroom link."),404
    if not session.get("user_id"): return redirect(url_for("login",next=url_for("join_by_link",room_code=room_code)))
    add_member(r,session["user_id"]); return redirect(url_for("room",room_code=room_code))

@app.route("/room/<room_code>")
def room(room_code):
    r=get_room(room_code)
    if not r:return render_template("not_found.html",message="Chatroom not found."),404
    if not session.get("user_id"):return redirect(url_for("login",next=request.path))
    if not member(r,session["user_id"]):
        if r.is_private:return render_template("join_room.html",room=r),403
        add_member(r,session["user_id"])
    members=RoomMember.query.filter_by(room_id=r.id).all()
    return render_template("room.html",room=r,members=members)

@app.route("/api/room/<room_code>/messages")
def history(room_code):
    if not session.get("user_id"):return jsonify(error="login_required"),401
    r=get_room(room_code)
    if not r or not member(r,session["user_id"]):return jsonify(error="not_allowed"),403
    ms=Message.query.filter_by(room_id=r.id).order_by(Message.created_at.desc()).limit(200).all(); ms.reverse()
    return jsonify(messages=[{"id":m.id,"username":m.user.username,"content":m.content,"timestamp":m.created_at.isoformat()+"Z"} for m in ms])

@app.route("/dm/<int:user_id>",methods=["GET","POST"])
def dm(user_id):
    g=guard()
    if g:return g
    u=me(); other=db.session.get(User,user_id)
    if not other or other.id==u.id:return render_template("not_found.html",message="User not found."),404
    if request.method=="POST":
        c=request.form.get("content","").strip()
        if c:db.session.add(DirectMessage(sender_id=u.id,receiver_id=other.id,content=c[:2000]));db.session.commit()
        return redirect(url_for("dm",user_id=other.id))
    ms=DirectMessage.query.filter(((DirectMessage.sender_id==u.id)&(DirectMessage.receiver_id==other.id))|((DirectMessage.sender_id==other.id)&(DirectMessage.receiver_id==u.id))).order_by(DirectMessage.created_at).all()
    for x in ms:
        if x.receiver_id==u.id:x.is_read=True
    db.session.commit()
    return render_template("direct_message.html",other=other,messages=ms)

@app.route("/health")
def health():return jsonify(status="ok",service="LinkChat")

@socketio.on("join_room")
def sjoin(data):
    uid=session.get("user_id"); code=(data or {}).get("room_code",""); r=get_room(code)
    if not uid or not r or not member(r,uid):return
    join_room(code); emit("presence",{"message":f"{me().username} joined the chat."},to=code)

@socketio.on("leave_room")
def sleave(data):
    uid=session.get("user_id"); code=(data or {}).get("room_code","")
    r=get_room(code)
    if not uid or not r:return
    leave_room(code); emit("presence",{"message":f"{me().username} left the chat."},to=code)

@socketio.on("send_message")
def smessage(data):
    uid=session.get("user_id"); code=(data or {}).get("room_code",""); c=(data or {}).get("content","").strip(); r=get_room(code)
    if not uid or not r or not member(r,uid) or not c:return
    m=Message(room_id=r.id,user_id=uid,content=c[:2000]);db.session.add(m);db.session.commit()
    emit("new_message",{"id":m.id,"username":me().username,"content":m.content,"timestamp":m.created_at.isoformat()+"Z"},to=code)

@socketio.on("typing")
def typing(data):
    uid=session.get("user_id"); code=(data or {}).get("room_code",""); r=get_room(code)
    if uid and r and member(r,uid):emit("typing",{"username":me().username},to=code,include_self=False)

with app.app_context(): db.create_all()

if __name__=="__main__":socketio.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",5000)),allow_unsafe_werkzeug=True)
