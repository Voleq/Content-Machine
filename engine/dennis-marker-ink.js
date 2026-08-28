/* Dennis · marker register · one engine, one source of truth.
   Every asset declares its own canvas; slots are recorded in source coords
   while drawing and transformed into canvas coords at render time.
   Used to bake flat PNGs — nothing here runs in a delivered asset. */
(function (global) {

  var C = { ink:'#232326', red:'#ff5247', grey:'#8f8c83', paper:'#f2f2ef', green:'#2fd576',
    /* WORLD palette. Physical objects in the room and nothing else — never a
       chart, a table, a card, a number, a label or a plate interior. All muted
       and low-contrast by construction so none of them competes with red. */
    world:{ postIt:'#e8d98a', mug:'#c98b52', can:'#7b9aa8', curtain:'#d8cfc0', plant:'#a8845c' } };

  /* the four registers. Geometry is shared — only the mark-making differs, so
     every slot keeps the same name and the same x/y/w/h in every register. */
  var PENS = {
    marker:    { name:'marker',    ink:'#232326', wMul:1,    rMul:1,    cap:'round', op:1,    passW:[1,0.62],     passR:[1,0.8],     passOp:[1,0.72] },
    ballpoint: { name:'ballpoint', ink:'#2b3242', wMul:0.36, rMul:0.62, cap:'round', op:0.94, passW:[1,0.7,0.46], passR:[1,1.5,2.2], passOp:[1,0.6,0.4] },
    grease:    { name:'grease',    ink:'#2a2724', wMul:1.55, rMul:1.5,  cap:'butt',  op:0.84, passW:[1,0.66],     passR:[1,1.35],    passOp:[1,0.6], broken:true },
    cutpaper:  { name:'cutpaper',  ink:'#232326', wMul:1.3,  rMul:0.42, cap:'butt',  op:1,    passW:[1,0.5],      passR:[1,0.7],     passOp:[1,0.5], shadow:true }
  };

  function prng(seed){ var s=(seed>>>0)||1; return function(){ s=(Math.imul(s^(s>>>15),1|s))>>>0; s=(s+Math.imul(s^(s>>>7),61|s))>>>0; return((s^(s>>>14))>>>0)/4294967296; }; }

  function Ink(kw,pen){ this.kw = kw || 1; this.pen = PENS[pen||'marker']; this.slots = []; this.guides = false; this.boil = 1; }
  var P = Ink.prototype;

  P.rpath = function(pts,rand,r){ var d='',i; for(i=0;i<pts.length;i++){ var jx=(rand()*2-1)*r, jy=(rand()*2-1)*r, x=pts[i][0]+jx, y=pts[i][1]+jy;
    if(i===0) d+='M'+x.toFixed(1)+','+y.toFixed(1);
    else { var px=pts[i-1][0], py=pts[i-1][1], mx=(px+pts[i][0])/2+(rand()*2-1)*r*1.4, my=(py+pts[i][1])/2+(rand()*2-1)*r*1.4;
      d+='Q'+mx.toFixed(1)+','+my.toFixed(1)+' '+x.toFixed(1)+','+y.toFixed(1); } } return d; };
  P._p = function(d,o){ o=o||{}; var s=o.s||(this.pen?this.pen.ink:C.ink), w=o.w==null?3:o.w, f=o.f||'none', op=o.op==null?1:o.op, cap=o.cap||'round';
    return '<path d="'+d+'" fill="'+f+'" stroke="'+s+'" stroke-width="'+w.toFixed(2)+'" stroke-linecap="'+cap+'" stroke-linejoin="round"'+(op!==1?' opacity="'+(+op.toFixed(3))+'"':'')+'/>'; };
  /* a soft wash of world colour under the ink of a physical object. Never
     used for data: reg() refuses to boil or wash anything in a data group. */
  P._wash = function(pts,rand,col,op){
    var d = this.rpath(pts,rand,4)+'Z';
    return '<path d="'+d+'" fill="'+col+'" stroke="none" opacity="'+(op==null?0.5:op)+'"/>'; };
  P._washEll = function(x,y,rx,ry,rand,col,op){
    return this._wash(this._ell(x,y,rx,ry,0,Math.PI*2,18),rand,col,op); };
  P._ext = function(pts,ov){ if(!ov||pts.length<2) return pts; var p=pts.map(function(q){return [q[0],q[1]];});
    var e=function(a,b){ var dx=a[0]-b[0], dy=a[1]-b[1], L=Math.hypot(dx,dy)||1; return [a[0]+dx/L*ov, a[1]+dy/L*ov]; };
    p[0]=e(p[0],p[1]); p[p.length-1]=e(p[p.length-1],p[p.length-2]); return p; };
  P._len = function(p){ var L=0,i; for(i=1;i<p.length;i++) L+=Math.hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1]); return L; };
  P._breakUp = function(pts,rand){ var n=pts.length, cut=Math.max(2,Math.floor(n*(0.44+rand()*0.18))),
      a=pts.slice(0,cut), b=pts.slice(Math.min(n-2,cut+1));
    return (a.length>1 && b.length>1) ? [a,b] : [pts]; };
  P._stroke = function(pts,rand,o){ o=o||{}; var pen=this.pen, K=this.kw, B=this.boil||1, Pt=this._ext(pts,(o.ov||0)*K),
      r=(o.r==null?2.6:o.r)*K*pen.rMul*B, w=(o.w==null?6:o.w)*K*pen.wMul*(1+(B-1)*0.55),
      base=(o.op==null?1:o.op)*pen.op, col=o.s||pen.ink, s='', i, j, runs=[Pt];
    if(pen.broken && Pt.length>2 && this._len(Pt)>210) runs=this._breakUp(Pt,rand);
    if(pen.shadow) s+=this._p(this.rpath(Pt.map(function(p){ return [p[0]+8,p[1]+11]; }),rand,r)+(o.close?'Z':''),{s:'#cdc9be',w:w*1.05,op:0.95,cap:pen.cap});
    for(i=0;i<pen.passW.length;i++){ for(j=0;j<runs.length;j++){
      var d=this.rpath(runs[j],rand,r*pen.passR[i]);
      if(o.close && runs.length===1) d+='Z';
      s+=this._p(d,{s:col,w:w*pen.passW[i],op:base*pen.passOp[i],cap:pen.cap}); } }
    return s; };
  P._ell = function(cx,cy,rx,ry,a0,a1,n){ n=n||26; var p=[],i; for(i=0;i<=n;i++){ var a=a0+(a1-a0)*i/n; p.push([cx+rx*Math.cos(a), cy+ry*Math.sin(a)]); } return p; };
  P._shift = function(dx,dy,inner){ return '<g transform="translate('+dx.toFixed(1)+','+dy.toFixed(1)+')">'+inner+'</g>'; };
  P._rot = function(deg,cx,cy,inner){ return '<g transform="rotate('+deg+' '+cx+' '+cy+')">'+inner+'</g>'; };
  P._box = function(rand,x,y,w,h,o){ o=o||{}; var ov=o.ov==null?Math.min(16,Math.max(7,w*0.014)):o.ov, W=o.w==null?7:o.w, r=o.r==null?3:o.r, s=o.s;
    return this._stroke([[x,y],[x+w,y]],rand,{w:W,r:r,s:s,ov:ov})
      + this._stroke([[x+w,y],[x+w,y+h]],rand,{w:W,r:r,s:s,ov:ov})
      + this._stroke([[x+w,y+h],[x,y+h]],rand,{w:W,r:r,s:s,ov:ov})
      + this._stroke([[x,y+h],[x,y]],rand,{w:W,r:r,s:s,ov:ov}); };
  P._head2 = function(x,y,ang,len,rand,o){ var a1=ang+Math.PI-0.42, a2=ang+Math.PI+0.42;
    return this._stroke([[x,y],[x+len*Math.cos(a1),y+len*Math.sin(a1)]],rand,o)
      + this._stroke([[x,y],[x+len*Math.cos(a2),y+len*Math.sin(a2)]],rand,o); };
  // records a slot in SOURCE coords; draws a guide only in review mode
  P.slot = function(name,x,y,w,h){ this.slots.push({ name:name, x:x, y:y, w:w, h:h });
    if(!this.guides) return '';
    var K=this.kw;
    return '<g data-guide="1"><rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" fill="none" stroke="'+C.grey+'" stroke-width="'+(3*K).toFixed(1)+'" stroke-dasharray="'+(16*K).toFixed(0)+' '+(12*K).toFixed(0)+'" opacity="0.55"/></g>'; };

  /* ── the room's furniture: the same objects in every viewpoint ─────── */
  P.monitorFront = function(rand,x,y,w,h,slotName){ var s=this._box(rand,x,y,w,h,{w:8});
    s+=this._box(rand,x+w*0.085,y+h*0.115,w-w*0.17,h-h*0.23,{w:4,r:2.4,ov:8});
    var cx=x+w/2, foot=h*0.18;
    s+=this._stroke([[cx,y+h],[cx-4,y+h+foot]],rand,{w:10,r:2.6});
    s+=this._stroke([[cx-w*0.16,y+h+foot+4],[cx+w*0.16,y+h+foot+2]],rand,{w:8,r:2.6,ov:12});
    if(slotName) s+=this.slot(slotName, x+w*0.105, y+h*0.145, w-w*0.21, h-h*0.29);
    return s; };
  P.monitorSide = function(rand,x,y,h){ var s=this._box(rand,x,y,46,h,{w:7,r:2.6});
    s+=this._stroke([[x,y+8],[x-16,y+14],[x-16,y+h-14],[x,y+h-8]],rand,{w:5,r:2.4});
    s+=this._stroke([[x+23,y+h],[x+21,y+h+58]],rand,{w:10,r:2.6});
    s+=this._stroke([[x-30,y+h+62],[x+78,y+h+60]],rand,{w:8,r:2.6,ov:12}); return s; };
  P.paperStack = function(rand,x,y,w,n){ var s='',i; for(i=0;i<(n||4);i++){ var dx=(rand()*2-1)*10, dy=-i*26;
      s+=this._stroke([[x+dx,y+dy],[x+w+dx*0.5,y+dy-5]],rand,{w:4,r:2.6,ov:6})
       + this._stroke([[x+w+dx*0.5,y+dy-5],[x+w-10+dx,y+dy+13],[x-8+dx,y+dy+15],[x+dx,y+dy]],rand,{w:4,r:2.6}); } return s; };
  P.paperStackTop = function(rand,x,y,w,h){ var s='',i; for(i=0;i<3;i++){ s+=this._rot(-4+i*3.5,x+w/2,y+h/2,this._box(rand,x+i*10,y+i*8,w,h,{w:5,r:2.6})); } return s; };
  P.mugFront = function(rand,x,y,k){ k=k||1;
    var s=this._wash([[x-46*k,y-8*k],[x+46*k,y-8*k],[x+40*k,y+68*k],[x-40*k,y+68*k]],rand,C.world.mug,0.42);
    s+=this._stroke([[x-46*k,y-8*k],[x+46*k,y-8*k],[x+40*k,y+68*k],[x-40*k,y+68*k]],rand,{w:6,r:2.6,close:true});
    s+=this._stroke([[x+46*k,y+6*k],[x+78*k,y+14*k],[x+70*k,y+48*k],[x+44*k,y+52*k]],rand,{w:5,r:2.4});
    s+=this._stroke([[x-16*k,y-30*k],[x-28*k,y-62*k],[x-12*k,y-88*k]],rand,{w:4,r:3.4,s:C.grey})
     + this._stroke([[x+18*k,y-30*k],[x+6*k,y-62*k],[x+22*k,y-88*k]],rand,{w:4,r:3.4,s:C.grey}); return s; };
  P.mugTop = function(rand,x,y,r){ var s=this._washEll(x,y,r*0.94,r*0.9,rand,C.world.mug,0.4);
    s+=this._stroke(this._ell(x,y,r,r*0.96,-0.2,Math.PI*2+0.4),rand,{w:7,r:3});
    s+=this._stroke(this._ell(x,y,r*0.68,r*0.66,0.3,Math.PI*2+0.9),rand,{w:5,r:2.6});
    s+=this._stroke([[x+r*0.92,y-r*0.3],[x+r*1.42,y-r*0.22],[x+r*1.44,y+r*0.3],[x+r*0.94,y+r*0.34]],rand,{w:5,r:2.4}); return s; };
  P.penTop = function(rand,x,y,len,ang){ var dx=Math.cos(ang)*len, dy=Math.sin(ang)*len;
    var s=this._stroke([[x,y],[x+dx,y+dy]],rand,{w:9,r:2.2});
    s+=this._stroke([[x+dx*0.86,y+dy*0.86],[x+dx*1.08,y+dy*1.08]],rand,{w:4,r:1.6});
    s+=this._stroke([[x+dx*0.2,y+dy*0.2],[x+dx*0.3,y+dy*0.3]],rand,{w:13,r:1.4,s:C.grey,op:0.55}); return s; };
  P.keebCorner = function(rand,x,y,w,h){ var s=this._box(rand,x,y,w,h,{w:6,r:2.6}),r,c;
    for(r=0;r<3;r++) for(c=0;c<5;c++){ s+=this._box(rand, x+26+c*(w-46)/5, y+24+r*(h-40)/3, (w-46)/5-14, (h-40)/3-16, {w:3,r:1.8,ov:4,s:C.grey}); } return s; };
  P.deskSlab = function(rand,x,y,w,d,legL,legR,legH){ var s=this._stroke([[x,y],[x+w,y]],rand,{w:9,r:3,ov:18});
    s+=this._stroke([[x,y+d],[x+w,y+d]],rand,{w:7,r:3,ov:18});
    s+=this._stroke([[x,y],[x,y+d]],rand,{w:7,r:2.4}) + this._stroke([[x+w,y],[x+w,y+d]],rand,{w:7,r:2.4});
    var self=this; [legL,legR].forEach(function(lx){
      s+=self._stroke([[lx,y+d],[lx-6,y+d+legH]],rand,{w:8,r:3});
      s+=self._stroke([[lx+46,y+d],[lx+50,y+d+legH]],rand,{w:8,r:3});
      s+=self._stroke([[lx-14,y+d+legH],[lx+58,y+d+legH-4]],rand,{w:6,r:2.6,ov:8}); });
    return s; };
  /* grounding: one wall/floor junction, and one light from the upper left so
     every shadow in every viewpoint falls down and to the right. */
  P.wallFloor = function(rand,y,w){ w=w||1080; return this._stroke([[-30,y],[w+30,y-9]],rand,{w:6,r:3,op:0.8,ov:12}); };
  /* the floor: the junction line, a baseboard under it. Two lines, no more —
     the large empty regions are slots and stay clear. x0/x1 keep it out of them. */
  P.floorPlane = function(rand,y,o){ o=o||{}; var w=o.w||1080, x0=o.x0==null?-30:o.x0, x1=o.x1==null?w+30:o.x1;
    var s=this._stroke([[x0,y+22],[x1,y+13]],rand,{w:4,r:2.4,s:C.grey,op:0.5,ov:10});
    if(o.recess) s+=this._stroke([[o.fromX,y+26],[o.toX,o.toY]],rand,{w:4,r:3,s:C.grey,op:0.34});
    return s; };
  /* ONE light source: a window off frame-left. Its light falls at the same
     angle as every shadow in the kit — 0.44 rad, down and to the right. */
  P.lightRays = function(rand,x,y,n,len,gap){ var s='',i,a=0.44; n=n||3; len=len||220; gap=gap||64;
    for(i=0;i<n;i++){ var ox=x+i*gap*0.55, oy=y+i*gap;
      s+=this._stroke([[ox,oy],[ox+Math.cos(a)*len,oy+Math.sin(a)*len]],rand,{w:4,r:2.8,s:C.grey,op:0.44-i*0.06}); }
    return s; };
  P.windowLeft = function(rand,y,h,rayLen){ var x=-96, w=386;
    var s=this._box(rand,x,y,w,h,{w:7,r:3});
    s+=this._stroke([[x+w*0.56,y],[x+w*0.56,y+h]],rand,{w:5,r:2.4});
    s+=this._stroke([[x,y+h*0.47],[x+w,y+h*0.43]],rand,{w:5,r:2.4});
    return s + this.lightRays(rand,x+w+16,y+h*0.54,3,rayLen||150,58); };
  P.shade = function(rand,x,y,len,ang){ ang=ang==null?0.44:ang; var dx=Math.cos(ang)*len, dy=Math.sin(ang)*len;
    return this._stroke([[x,y],[x+dx,y+dy]],rand,{w:5,r:2.2,s:C.grey,op:0.55}); };
  P.shadePair = function(rand,x,y,len){ return this.shade(rand,x,y,len) + this.shade(rand,x+len*0.42,y-len*0.1,len*0.7); };
  P.blot = function(rand,x,y,r){ var p=this._ell(x,y,r,r*(0.72+rand()*0.5),0,Math.PI*2,14);
    return this._p(this.rpath(p,rand,r*0.38)+'Z',{f:this.pen.ink,w:0,s:'none'}); };
  P.clip = function(rand,x,y,k){ k=k||1; // bulldog clip
    var s=this._stroke([[x-32*k,y],[x+32*k,y],[x+28*k,y+34*k],[x-28*k,y+34*k]],rand,{w:6,r:2.4,close:true});
    s+=this._stroke([[x-18*k,y-2*k],[x-26*k,y-30*k]],rand,{w:5,r:2.4,s:C.grey})
     + this._stroke([[x+18*k,y-2*k],[x+26*k,y-30*k]],rand,{w:5,r:2.4,s:C.grey});
    return s; };
  P.pin = function(rand,x,y,k){ k=k||1;
    return this._stroke(this._ell(x,y,13*k,13*k,0,Math.PI*2),rand,{w:6,r:2,close:true})
      + this._stroke(this._ell(x,y,5*k,5*k,0,Math.PI*2),rand,{w:4,r:1.4,s:C.grey,close:true}); };
  P.paperclip = function(rand,x,y,k){ k=k||1;
    var s=this._stroke([[x,y+52*k],[x,y+14*k],[x+13*k,y],[x+26*k,y+14*k],[x+26*k,y+58*k]],rand,{w:5,r:2.2});
    s+=this._stroke([[x+9*k,y+50*k],[x+9*k,y+20*k],[x+15*k,y+14*k],[x+19*k,y+20*k],[x+19*k,y+40*k]],rand,{w:4,r:2,s:C.grey});
    return s; };
  P.foldCorner = function(rand,x,y,k,dir){ k=k||1; dir=dir||1; // dir 1 = fold at bottom-right
    return this._stroke([[x-46*k*dir,y],[x,y],[x,y-46*k]],rand,{w:6,r:2.4})
      + this._stroke([[x-46*k*dir,y],[x,y-46*k]],rand,{w:5,r:2.6,s:C.grey}); };
  P.tornEdge = function(rand,x1,y1,x2,y2,amp){ amp=amp||12; var pts=[[x1,y1]], t=0, i;
    while(t<1){ t += 0.045 + rand()*0.085; if(t>1) t=1;
      pts.push([x1+(x2-x1)*t + (rand()-0.5)*amp*0.6, y1+(y2-y1)*t + (rand()-0.5)*amp*1.9]); }
    var s=this._stroke(pts,rand,{w:5,r:1.7});
    for(i=1;i<pts.length-1;i+=2) s+=this._stroke([[pts[i][0],pts[i][1]],[pts[i][0]+(rand()-0.5)*9, pts[i][1]-(4+rand()*8)]],rand,{w:3,r:1.3,s:C.grey,op:0.65});
    return s; };
  P.lamp = function(rand,x,y,on){ // x,y = base on the desk
    var s=this._stroke([[x-40,y],[x+40,y-2]],rand,{w:7,r:2.4,ov:8});
    s+=this._stroke([[x,y-4],[x+6,y-150],[x+40,y-206]],rand,{w:7,r:3});
    s+=this._stroke([[x+40,y-206],[x+120,y-240],[x+96,y-176],[x+30,y-176]],rand,{w:7,r:2.8,close:true});
    if(on){ s+=this._stroke([[x+118,y-166],[x+150,y-150]],rand,{w:5,r:2.4,s:C.grey})
      + this._stroke([[x+92,y-152],[x+104,y-116]],rand,{w:5,r:2.4,s:C.grey})
      + this._stroke([[x+50,y-150],[x+44,y-114]],rand,{w:5,r:2.4,s:C.grey}); }
    return s; };
  P.windowFrame = function(rand,x,y,w,h,mode){ var s=this._box(rand,x,y,w,h,{w:8});
    s+=this._stroke([[x+w/2,y],[x+w/2,y+h]],rand,{w:6,r:2.4});
    if(mode==='night'){ var i; for(i=1;i<6;i++) s+=this._stroke([[x+10,y+h*i/6],[x+w-10,y+h*i/6-4]],rand,{w:4,r:2.4,s:C.grey,op:0.7}); }
    else if(mode==='dawn'){ s+=this._stroke([[x+12,y+h*0.66],[x+w-12,y+h*0.66-6]],rand,{w:5,r:2.6,s:C.grey});
      s+=this._stroke(this._ell(x+w*0.68,y+h*0.66,58,58,Math.PI,Math.PI*2),rand,{w:5,r:2.6,s:C.grey}); }
    else if(mode==='dark'){ var j; for(j=0;j<7;j++){ var t=j/6; s+=this._stroke([[x+10+t*(w-20),y+8],[x+10+t*(w-20)-40,y+h-8]],rand,{w:4,r:2.6,s:C.grey,op:0.55}); } }
    return s; };

  /* ── GROUP A · the room, authored for a tall frame 1080×1920 ───────── */
  P.roomWide = function(rand){ var s='';
    s+=this.wallFloor(rand,1244);
    s+=this.floorPlane(rand,1244,{x1:790});
    s+=this.windowLeft(rand,228,392,150);
    s+=this.deskSlab(rand,-40,1310,1160,78,140,820,560);
    s+=this.monitorFront(rand,30,917,370,330,'screen');
    s+=this.mugFront(rand,850,1233,1.05);
    s+=this.paperStack(rand,960,1300,122,4);
    s+=this.shadePair(rand,404,1258,86);
    s+=this.shade(rand,930,1246,64);
    s+=this.slot('figure',400,550,400,760);
    return s; };
  P.roomSide = function(rand){ var s='';
    s+=this.wallFloor(rand,1262);
    s+=this.floorPlane(rand,1262,{x0:80,x1:440});
    s+=this.windowLeft(rand,200,400,150);
    s+=this.deskSlab(rand,180,1330,940,70,520,980,560);
    s+=this.monitorSide(rand,940,924,340);
    s+=this.paperStack(rand,470,1322,210,4);
    s+=this.mugFront(rand,800,1258,1);
    // chair, clear of the desk, facing it
    s+=this._stroke([[60,1450],[430,1442]],rand,{w:9,r:3,ov:14});
    s+=this._stroke([[60,1464],[428,1456]],rand,{w:5,r:2.4,ov:8});
    s+=this._stroke([[400,1456],[414,1900]],rand,{w:8,r:3}) + this._stroke([[92,1458],[76,1900]],rand,{w:8,r:3});
    s+=this._stroke([[74,1446],[38,1040]],rand,{w:9,r:3});
    s+=this._stroke([[20,1032],[78,1036]],rand,{w:9,r:2.4,ov:6});
    s+=this._stroke([[48,1218],[98,1220]],rand,{w:6,r:2.2,s:C.grey,ov:4});
    s+=this.shadePair(rand,690,1284,88);
    s+=this.shade(rand,986,1272,60);
    s+=this.slot('figure-seated',60,860,410,590);
    return s; };
  P.roomOver = function(rand){ var s='';
    s+=this.wallFloor(rand,1190);
    s+=this.floorPlane(rand,1190);
    s+=this.lightRays(rand,-40,26,3,206,58);
    s+=this._stroke([[0,1268],[1080,1258]],rand,{w:8,r:3,ov:20});
    s+=this.shadePair(rand,596,1224,92);
    s+=this.monitorFront(rand,80,300,920,760,'screen');
    // back of head, neck and one shoulder, low in frame
    s+=this._stroke([[0,1920],[92,1806],[268,1748],[420,1738]],rand,{w:9,r:4});
    s+=this._stroke([[566,1740],[746,1776],[900,1854],[980,1920]],rand,{w:9,r:4});
    s+=this._stroke(this._ell(468,1424,236,244,-0.18,Math.PI*2+0.42),rand,{w:9,r:4.4});
    s+=this._stroke([[398,1660],[404,1734]],rand,{w:7,r:3}) + this._stroke([[540,1656],[534,1732]],rand,{w:7,r:3});
    s+=this._stroke([[458,1176],[422,1112],[490,1136],[466,1184]],rand,{w:7,r:3.4});
    s+=this._stroke([[250,1782],[272,1840],[288,1886]],rand,{w:5,r:3,s:C.grey});
    return s; };
  P.deskTop = function(rand){ var s='';
    s+=this._stroke([[0,104],[1080,96]],rand,{w:8,r:3.4,ov:20});
    s+=this.lightRays(rand,-40,486,3,108,56);
    s+=this._stroke([[0,1856],[1080,1848]],rand,{w:9,r:3.4,ov:20});
    s+=this._stroke([[70,1700],[1010,1692]],rand,{w:3,r:4,s:C.grey,op:0.5});
    s+=this.mugTop(rand,204,268,104);
    s+=this.penTop(rand,120,1656,262,-0.22);
    s+=this.paperStackTop(rand,742,150,296,236);
    s+=this.keebCorner(rand,700,1672,392,232);
    s+=this.shade(rand,300,352,96) + this.shade(rand,1042,404,84) + this.shade(rand,244,1712,72);
    s+=this.slot('pages',140,470,800,1040);
    return s; };
  P.atSheet = function(rand){ var s='';
    s+=this.wallFloor(rand,1812);
    s+=this.floorPlane(rand,1812,{x0:664,x1:1110});
    s+=this.lightRays(rand,-44,296,3,100,60);
    var sheet = this._box(rand,120,116,940,1120,{w:9,r:3.4})
      + this._stroke([[152,286],[1030,278]],rand,{w:6,r:3,ov:14});
    s+=this._rot(-1.1,590,676,sheet);
    s+=this.slot('sheet',160,310,860,840);
    s+=this._stroke(this._ell(154,146,15,15,0,Math.PI*2),rand,{w:6,r:2,close:true});
    s+=this._stroke(this._ell(1026,132,15,15,0,Math.PI*2),rand,{w:6,r:2,close:true});
    s+=this.shade(rand,1046,1252,92);
    s+=this.slot('figure',80,1200,560,680);
    return s; };

  /* ── GROUP B · the host, transparent cut-out, canvas 720×900 ───────── */
  P.hBody = function(rand){ var s=this._stroke([[416,470],[584,470]],rand,{w:7,r:3,ov:12})
    + this._stroke([[584,470],[596,706]],rand,{w:7,r:3,ov:12})
    + this._stroke([[596,706],[404,706]],rand,{w:7,r:3,ov:12})
    + this._stroke([[404,706],[416,470]],rand,{w:7,r:3,ov:12});
    s+=this._stroke([[500,418],[500,468]],rand,{w:7,r:2});
    s+=this._stroke([[456,706],[452,800],[446,884],[422,894]],rand,{w:7,r:3});
    s+=this._stroke([[544,706],[548,800],[554,884],[578,894]],rand,{w:7,r:3});
    return s; };
  P.hBodySeated = function(rand){ // genuinely seated: hips low, thighs forward, shins down
    var s=this._stroke([[424,480],[590,472]],rand,{w:7,r:3,ov:12})
      + this._stroke([[590,472],[602,700]],rand,{w:7,r:3,ov:12})
      + this._stroke([[602,700],[414,708]],rand,{w:7,r:3,ov:12})
      + this._stroke([[414,708],[424,480]],rand,{w:7,r:3,ov:12});
    s+=this._stroke([[502,420],[500,478]],rand,{w:7,r:2});
    // near thigh → knee → shin → foot
    s+=this._stroke([[470,712],[610,726],[706,732]],rand,{w:7,r:3});
    s+=this._stroke([[706,732],[716,846],[720,884]],rand,{w:7,r:3});
    s+=this._stroke([[694,890],[760,886]],rand,{w:6,r:2.6,ov:8});
    // far leg, a little behind
    s+=this._stroke([[466,724],[598,748],[672,756]],rand,{w:6,r:3});
    s+=this._stroke([[672,756],[680,856],[684,888]],rand,{w:6,r:3});
    s+=this._stroke([[660,894],[718,890]],rand,{w:5,r:2.6,ov:8});
    return s; };
  P.hHead = function(rand){ var s=this._stroke(this._ell(500,300,118,128,-0.15,Math.PI*2+0.55),rand,{w:7,r:4});
    s+=this._stroke([[500,176],[480,146],[514,158],[496,182]],rand,{w:6,r:3.4}); return s; };
  P.hHeadSide = function(rand,dir){ var g=dir==='right'?1:-1;
    var s=this._stroke(this._ell(500,300,116,128,-0.15,Math.PI*2+0.55),rand,{w:7,r:4});
    s+=this._stroke([[500+g*96,322],[500+g*126,342],[500+g*96,358]],rand,{w:5,r:2.4});
    var tx=500-g*30; s+=this._stroke([[tx,176],[tx-g*20,146],[tx+g*14,158],[tx-g*4,182]],rand,{w:6,r:3.4});
    s+=this._stroke(this._ell(500-g*116,306,11,19,0,Math.PI*2),rand,{w:4.6,r:2.2}); return s; };
  /* lid 0 = open, heavy lid, gaze slightly down (the default)
     lid 1 = half, mid-blink · lid 2 = fully closed, for the blink only */
  P.hEyes = function(rand,lid){ var Lx=456,Rx=544,Ey=288,self=this;
    var open=function(x){
      /* the eye itself: an open almond, pupil low in it, lid cutting the top */
      var s=self._stroke([[x-24,Ey+1],[x-9,Ey-9],[x+11,Ey-9],[x+24,Ey+2],[x+8,Ey+12],[x-10,Ey+12]],rand,{w:5,r:2,close:true});
      s+=self._stroke(self._ell(x+1,Ey+5,7,7,0,Math.PI*2),rand,{w:4,r:1.4,close:true});
      s+=self._stroke([[x-26,Ey-4],[x-6,Ey-12],[x+14,Ey-11],[x+26,Ey-3]],rand,{w:6.5,r:2.2});
      return s; };
    var eye=function(x){ return lid>=2 ? self._stroke([[x-24,Ey+4],[x+24,Ey+3]],rand,{w:5,r:1.8,ov:4})
      : lid===1 ? self._stroke([[x-23,Ey],[x,Ey+5],[x+23,Ey]],rand,{w:5,r:1.8})
      : open(x); };
    return eye(Lx)+eye(Rx)
      + this._stroke([[Lx-18,316],[Lx,322],[Lx+18,316]],rand,{w:4,r:2.2,s:C.grey})
      + this._stroke([[Rx-18,316],[Rx,322],[Rx+18,316]],rand,{w:4,r:2.2,s:C.grey}); };
  P.hEyesSide = function(rand,dir,lid){ var g=dir==='right'?1:-1, Ey=288, nx=500+g*64, fx=500+g*6, self=this;
    var eye=function(x,k){
      if(lid>=2) return self._stroke([[x-20*k,Ey+4],[x+20*k,Ey+3]],rand,{w:5,r:1.8,ov:4});
      if(lid===1) return self._stroke([[x-20*k,Ey],[x,Ey+6],[x+20*k,Ey]],rand,{w:5,r:1.8});
      var s=self._stroke([[x-20*k,Ey+1],[x-7*k,Ey-8],[x+10*k,Ey-8],[x+20*k,Ey+2],[x+6*k,Ey+11],[x-9*k,Ey+11]],rand,{w:5,r:2,close:true});
      s+=self._stroke(self._ell(x+g*3*k,Ey+5,6*k,6*k,0,Math.PI*2),rand,{w:3.8,r:1.3,close:true});
      s+=self._stroke([[x-22*k,Ey-4],[x-4*k,Ey-11],[x+13*k,Ey-10],[x+22*k,Ey-3]],rand,{w:6,r:2.2});
      return s; };
    return eye(nx,1)+eye(fx,0.78)
      + this._stroke([[nx-15,316],[nx,321],[nx+15,316]],rand,{w:4,r:2.2,s:C.grey})
      + this._stroke([[fx-12,315],[fx,320],[fx+12,315]],rand,{w:3.6,r:2.2,s:C.grey}); };
  P.hArm = function(rand,arm){ var self=this, L=function(pts,w){ return self._stroke(pts,rand,{w:w||7,r:3}); }, s='';
    if(arm==='rest') s+=L([[418,500],[404,594],[400,650]])+L([[582,500],[598,594],[604,650]]);
    else if(arm==='gesture') s+=L([[418,500],[404,594],[400,650]])+L([[582,500],[668,540],[712,566]])+this._stroke([[712,566],[742,558],[738,584],[714,584]],rand,{w:5,r:2.4});
    else if(arm==='gesture-hi') s+=L([[418,500],[404,594],[400,650]])+L([[582,500],[672,496],[724,478]])+this._stroke([[724,478],[754,468],[752,494],[726,496]],rand,{w:5,r:2.4});
    else if(arm==='present-right') s+=L([[418,500],[404,590],[398,640]])+L([[582,500],[648,462],[712,420],[762,392]])+this._stroke([[762,392],[792,382],[796,408],[770,412]],rand,{w:5,r:2.4});
    else if(arm==='present-right-lo') s+=L([[418,500],[404,590],[398,640]])+L([[582,500],[656,486],[730,468],[782,458]])+this._stroke([[782,458],[812,452],[814,478],[788,480]],rand,{w:5,r:2.4});
    else if(arm==='point-up') s+=L([[418,500],[404,594],[400,650]])+L([[582,494],[672,404],[742,318]])+this._stroke([[742,318],[760,290],[774,300],[758,326]],rand,{w:5,r:2.4});
    else if(arm==='point-up-b') s+=L([[418,500],[404,594],[400,650]])+L([[582,494],[678,412],[752,332]])+this._stroke([[752,332],[772,306],[784,318],[768,342]],rand,{w:5,r:2.4});
    else if(arm==='hold-mug'){ s+=this._stroke([[424,508],[398,600],[394,664]],rand,{w:7,r:3})
      + this._stroke([[588,506],[650,584],[622,528]],rand,{w:7,r:3}); s+=this.mugFront(rand,656,504,0.62); }
    return s; };
  P.hMouth = function(rand,kind){ if(kind==='open') return this._stroke(this._ell(500,366,17,20,0,Math.PI*2),rand,{w:5,r:2,close:true});
    if(kind==='mid') return this._stroke(this._ell(500,362,16,9,0,Math.PI*2),rand,{w:4.6,r:1.6,close:true});
    return this._stroke([[470,360],[530,358]],rand,{w:5,r:1.8,ov:4}); };
  P.host = function(rand,key,f){ var bob=[0,-3,0,2][f%4], m, a, lid;
    if(key==='talking-to-camera'){ m=['closed','mid','open','mid','open','mid'][f]; a=['rest','rest','gesture','gesture','gesture-hi','rest'][f];
      return this._shift(0,bob, this.hBody(rand)+this.hArm(rand,a)+this.hHead(rand)+this.hEyes(rand,f===4?1:0)+this.hMouth(rand,m)); }
    if(key==='talking-at-screen'){ m=['mid','open','mid','open','closed'][f]; a=['present-right','present-right','present-right-lo','present-right','present-right-lo'][f];
      return this._shift(0,bob, this.hBody(rand)+this.hArm(rand,a)+this.hHeadSide(rand,'right')+this.hEyesSide(rand,'right',f===3?1:0)+this._shift(40,2,this.hMouth(rand,m))); }
    if(key==='pointing-at-sheet'){ m=['open','mid','open','mid','closed'][f]; a=['point-up','point-up-b','point-up','point-up-b','point-up'][f];
      return this._shift(0,bob, this.hBody(rand)+this.hArm(rand,a)+this.hHeadSide(rand,'right')+this.hEyesSide(rand,'right',f===2?1:0)+this._shift(40,2,this.hMouth(rand,m))); }
    lid=[0,0,1,2][f];
    return this._shift(0,f===3?1:0, this.hBodySeated(rand)+this.hArm(rand,'hold-mug')+this.hHead(rand)+this.hEyes(rand,lid)+this.hMouth(rand,'closed'));
  };
  P.hostClosed = function(rand,key){
    if(key==='talking-to-camera') return this.hBody(rand)+this.hArm(rand,'rest')+this.hHead(rand)+this.hEyes(rand,0)+this.hMouth(rand,'closed');
    if(key==='talking-at-screen') return this.hBody(rand)+this.hArm(rand,'present-right')+this.hHeadSide(rand,'right')+this.hEyesSide(rand,'right',0)+this._shift(40,2,this.hMouth(rand,'closed'));
    if(key==='pointing-at-sheet') return this.hBody(rand)+this.hArm(rand,'point-up')+this.hHeadSide(rand,'right')+this.hEyesSide(rand,'right',0)+this._shift(40,2,this.hMouth(rand,'closed'));
    return this.hBodySeated(rand)+this.hArm(rand,'hold-mug')+this.hHead(rand)+this.hEyes(rand,0)+this.hMouth(rand,'closed');
  };

  /* ── GROUP C · the props ──────────────────────────────────────────── */
  P.pageCorporate = function(rand){
    var page=this._stroke([[60,64],[940,50]],rand,{w:8,r:3,ov:14})
      + this._stroke([[940,50],[948,1136]],rand,{w:8,r:3,ov:14})
      + this._stroke([[848,1244],[54,1236]],rand,{w:8,r:3,ov:14})
      + this._stroke([[54,1236],[60,64]],rand,{w:8,r:3,ov:14})
      + this._stroke([[948,1136],[858,1150],[848,1244]],rand,{w:7,r:3})
      + this._stroke([[858,1150],[946,1140]],rand,{w:5,r:2.6,s:C.grey})
      + this._stroke([[122,336],[880,326]],rand,{w:6,r:2.6,ov:12});
    var g=this._rot(-2.6,500,650,page);
    // slots are recorded unrotated, matching the compositor's straight boxes
    return g + this.slot('headline',118,146,764,158)
      + this.slot('body-1',118,394,764,92) + this.slot('body-2',118,520,764,92) + this.slot('body-3',118,646,764,92); };
  P.pageInstitutional = function(rand){
    var page=this._box(rand,58,52,884,1192,{w:8})
      + this._box(rand,140,140,720,1014,{w:3,r:2.4,ov:6,s:C.grey})
      + this._stroke(this._ell(500,232,58,58,-0.2,Math.PI*2+0.4),rand,{w:6,r:3})
      + this._stroke(this._ell(500,232,38,38,0.4,Math.PI*2+0.8),rand,{w:4,r:2.4,s:C.grey})
      + this._stroke([[186,470],[814,464]],rand,{w:5,r:2.4,ov:10});
    return this._rot(1.4,500,650,page)
      + this.slot('headline',182,318,636,118)
      + this.slot('body-1',182,506,636,78) + this.slot('body-2',182,606,636,78)
      + this.slot('body-3-circled',182,706,636,78) + this.slot('body-4',182,806,636,78); };
  P.sheetFrame = function(rand){ return this._box(rand,60,58,1280,782,{w:9})
    + this._stroke([[74,212],[1326,204]],rand,{w:7,r:3,ov:16})
    + this.clip(rand,700,32,1.15)
    + this.slot('interior',84,232,1232,586); };
  P.monitorProp = function(rand){ return this.monitorFront(rand,60,58,1480,744,'screen')
    + this._stroke(this._ell(150,752,13,13,0,Math.PI*2),rand,{w:5,r:1.6,s:C.grey,close:true}); };
  P.stampProp = function(rand){ var self=this, x=58, y=74, w=684, h=344;
    // an ink impression, not a rectangle: each edge breaks up, heavier where the
    // stamp bit down (bottom-left) and missing where it lifted (top-right)
    // an ink impression, not a rectangle: the edge wanders, ink pools where the
    // stamp bit down (bottom-left) and drops out where it lifted (top-right)
    function edge(x1,y1,x2,y2,bite){
      var len=Math.hypot(x2-x1,y2-y1), ux=(x2-x1)/len, uy=(y2-y1)/len, px=-uy, py=ux, i,
          n=9, base=[];
      for(i=0;i<=n;i++){ var t=i/n, o=(rand()*2-1)*6.5;
        base.push([x1+(x2-x1)*t+px*o, y1+(y2-y1)*t+py*o]); }
      var at=function(t){ var f=t*n, k=Math.min(n-1,Math.floor(f)), r=f-k;
        return [base[k][0]+(base[k+1][0]-base[k][0])*r, base[k][1]+(base[k+1][1]-base[k][1])*r]; };
      // one to three drop-outs, unevenly placed, more of them where it lifted
      var gaps=[], gn=1+Math.round(rand()*(bite<0.5?2:1));
      for(i=0;i<gn;i++){ var g0=0.08+rand()*0.78, gl=0.04+rand()*(0.09-bite*0.05); gaps.push([g0,Math.min(0.97,g0+gl)]); }
      gaps.sort(function(a,b){ return a[0]-b[0]; });
      var runs=[], cur=0.0;
      gaps.forEach(function(g){ if(g[0]>cur+0.03) runs.push([cur,g[0]]); cur=Math.max(cur,g[1]); });
      if(cur<0.98) runs.push([cur,1]);
      var out='';
      runs.forEach(function(r){
        var seg=[], t; for(t=r[0]; t<=r[1]+1e-6; t+=0.05) seg.push(at(Math.min(1,t)));
        if(seg.length<2) seg.push(at(Math.min(1,r[1])));
        // two passes: the body of the impression, then pressure variation on top
        out += self._stroke(seg,rand,{w:9+bite*8, r:1.6, op:0.5+bite*0.3});
        var m=Math.floor(seg.length/2);
        if(seg.length>3) out += self._stroke(seg.slice(0,m+1),rand,{w:6+bite*9+rand()*4, r:1.4, op:0.72+bite*0.28});
        if(seg.length>3) out += self._stroke(seg.slice(m),rand,{w:5+bite*6+rand()*5, r:1.4, op:0.62+bite*0.32});
      });
      return out; }
    var g = edge(x+6,y+4,x+w-10,y,0.18)
      + edge(x+w-4,y+8,x+w-10,y+h-6,0.5)
      + edge(x+w-14,y+h,x+8,y+h-6,0.98)
      + edge(x+2,y+h-12,x,y+6,0.72);
    g += this.blot(rand,x+12,y+h-14,17) + this.blot(rand,x+34,y+h-6,11) + this.blot(rand,x+w-22,y+h-18,9);
    g += this.blot(rand,x+3,y+72,7) + this.blot(rand,x+w-8,y+h-96,6);
    var i; for(i=0;i<9;i++){ var sx=x+18+rand()*(w-40), sy=y+16+rand()*(h-30);
      g += this.blot(rand,sx,sy,1.6+rand()*2.4); }
    return this._rot(-6.5,400,250,g) + this.slot('stamp-text',146,158,508,176); };
  P.cardGuidance = function(rand){ return this._box(rand,40,40,620,380,{w:8})
    + this.paperclip(rand,556,12,1)
    + this.slot('label',88,88,326,68) + this.slot('figure',88,196,524,164); };
  P.chainOfThree = function(rand){ var s='', xs=[380,872,1364], self=this;
    xs.forEach(function(x,i){ s+=self._box(rand,x,118,380,424,{w:8}); s+=self.slot('text-'+(i+1), x+34,152,312,356); });
    [[770,860],[1262,1352]].forEach(function(p){ s+=self._stroke([[p[0],330],[p[1],330]],rand,{w:8,r:2.4})+self._head2(p[1],330,0,26,rand,{w:8,r:1.6}); });
    s+=this.pin(rand,398,136,1);
    return s + this.slot('figure',64,118,286,424); };
  P.cardConsequence = function(rand){ return this._box(rand,30,30,460,560,{w:8})
    + this.pin(rand,260,-2,1)
    + this.slot('label',72,72,376,152) + this.slot('mark',180,300,160,160); };
  P.cardConsequenceB = function(rand){ // same canvas and slot names, different shape and edge
    var s=this._stroke([[30,30],[492,26]],rand,{w:8,r:3,ov:10});
    s+=this._stroke([[496,32],[500,470]],rand,{w:8,r:3,ov:8});
    s+=this._stroke([[500,470],[430,566]],rand,{w:8,r:3});
    s+=this.tornEdge(rand,428,568,40,560,15);
    s+=this._stroke([[34,556],[30,30]],rand,{w:8,r:3,ov:8});
    s+=this._stroke([[434,486],[496,472]],rand,{w:5,r:2.6,s:C.grey})
     + this._stroke([[434,486],[430,566]],rand,{w:5,r:2.6,s:C.grey});
    s+=this.paperclip(rand,58,6,1);
    return s + this.slot('label',72,72,376,152) + this.slot('mark',180,300,160,160); };
  P.comparePlate = function(rand){ return this._box(rand,60,80,640,540,{w:8}) + this._box(rand,900,80,640,540,{w:8})
    + this.foldCorner(rand,1540,620,1,1)
    + this.slot('left',102,122,556,456) + this.slot('right',942,122,556,456) + this.slot('gap',730,268,140,164); };

  /* ── GROUP D · full-frame stages, 9:16 ────────────────────────────── */
  P.sheetTall = function(rand){ var x=70, y=110, w=940, h=1230, s='';
    s+=this._box(rand,x,y,w,h,{w:9});
    s+=this._stroke([[x+24,y+152],[x+w-24,y+144]],rand,{w:7,r:3,ov:16});
    s+=this.pin(rand,x+44,y+36,1.1) + this.pin(rand,x+w-44,y+32,1.1);
    s+=this.clip(rand,x+w/2,y-30,1.25);
    var ix=x+30, iy=y+182, iw=w-60, ih=h-212, bh=ih/6, i;
    s+=this.slot('interior',ix,iy,iw,ih);
    for(i=0;i<6;i++) s+=this.slot('row-'+(i+1), ix, Math.round(iy+i*bh), iw, Math.round(bh));
    s+=this.wallFloor(rand,1476);
    s+=this.shade(rand,x+w+10,1344,96);
    s+=this.slot('figure',560,1240,470,660);
    return s; };
  P.screenFull = function(rand){ var s=this._box(rand,26,26,1028,1868,{w:10});
    s+=this._box(rand,86,86,908,1748,{w:5,r:2.4,ov:8});
    s+=this._stroke(this._ell(540,1864,12,12,0,Math.PI*2),rand,{w:5,r:1.6,s:C.grey,close:true});
    s+=this.slot('screen',104,104,872,1712);
    return s; };
  P.numberFull = function(rand){ var s=this.wallFloor(rand,1672);
    s+=this.slot('label',300,404,480,110);
    s+=this.slot('figure',90,560,900,760);
    var host=this.hBody(rand)+this.hArm(rand,'rest')+this.hHead(rand)+this.hEyes(rand,0)+this.hMouth(rand,'closed');
    s+='<g transform="rotate(-4 540 1676) translate(330,1300) scale(0.42)">'+host+'</g>';
    s+=this.shade(rand,626,1678,96);
    return s; };

  /* ── channel identity ─────────────────────────────────────────────── */
  P.avatarFace = function(rand,variant){
    var s=this._stroke(this._ell(500,300,118,128,-0.15,Math.PI*2+0.55),rand,{w:11,r:4});
    s+=this._stroke([[500,176],[478,142],[516,156],[496,182]],rand,{w:9,r:3.4});
    var Lx=456, Rx=544, Ey=288;
    if(variant==='mid-blink'){
      s+=this._stroke([[Lx-26,Ey+3],[Lx+26,Ey+2]],rand,{w:7.5,r:1.8,ov:4})
       + this._stroke([[Rx-26,Ey+3],[Rx+26,Ey+2]],rand,{w:7.5,r:1.8,ov:4});
    } else if(variant==='unimpressed'){
      s+=this._stroke([[Lx-24,Ey-2],[Lx,Ey+7],[Lx+24,Ey-3]],rand,{w:7,r:2})
       + this._stroke([[Rx-24,Ey-3],[Rx,Ey+6],[Rx+24,Ey-2]],rand,{w:7,r:2});
      s+=this._stroke([[Lx-26,Ey-34],[Lx+22,Ey-32]],rand,{w:7,r:2,ov:3})
       + this._stroke([[Rx-22,Ey-32],[Rx+26,Ey-35]],rand,{w:7,r:2,ov:3});
    } else if(variant==='brow-raised'){
      s+=this._stroke([[Lx-24,Ey-5],[Lx,Ey+10],[Lx+24,Ey-5]],rand,{w:7,r:2.2})
       + this._stroke([[Rx-23,Ey-4],[Rx,Ey+8],[Rx+23,Ey-4]],rand,{w:7,r:2.2});
      s+=this._stroke([[Lx-26,Ey-31],[Lx+22,Ey-30]],rand,{w:7,r:2,ov:3});
      s+=this._stroke([[Rx-26,Ey-44],[Rx-2,Ey-58],[Rx+26,Ey-48]],rand,{w:7,r:2.2});
    } else {
      s+=this._stroke([[Lx-24,Ey-5],[Lx,Ey+10],[Lx+24,Ey-5]],rand,{w:7,r:2.2})
       + this._stroke([[Rx-24,Ey-5],[Rx,Ey+10],[Rx+24,Ey-5]],rand,{w:7,r:2.2});
    }
    s+=this._stroke([[Lx-19,318],[Lx,324],[Lx+19,318]],rand,{w:5.5,r:2.2,s:C.grey})
     + this._stroke([[Rx-19,318],[Rx,324],[Rx+19,318]],rand,{w:5.5,r:2.2,s:C.grey});
    s+= variant==='unimpressed'
      ? this._stroke([[468,360],[512,357],[530,365]],rand,{w:7,r:1.8,ov:4})
      : this._stroke([[468,360],[532,358]],rand,{w:7,r:1.8,ov:4});
    return s; };
  // 2048×1152. Furniture lives in the outer thirds and below the safe area.
  P.banner = function(rand,mode){
    var lampOn = mode!=='midday', win = mode==='3am' ? 'dark' : mode==='dawn' ? 'dawn' : mode==='late' ? 'night' : 'clear';
    var deskY = 880, s='';
    // window sits behind everything, above the safe band
    s+=this.windowFrame(rand,1560,96,420,286,win);
    // Dennis, seated side-on at the desk, right outer third
    var host = this.hBodySeated(rand)+this.hArm(rand,'hold-mug')+this.hHeadSide(rand,'left')+this.hEyesSide(rand,'left',mode==='late'?1:0)+this._shift(-40,2,this.hMouth(rand,'closed'));
    var k=0.55, tx = (mode==='late'?1812:1800) - 500*k, ty = deskY - 704*k + (mode==='late'?14:0);
    s+='<g transform="translate('+tx.toFixed(1)+','+ty.toFixed(1)+') scale('+k+')">'+host+'</g>';
    // the desk occludes everything below its top edge
    s+='<rect x="0" y="'+deskY+'" width="2048" height="'+(1152-deskY)+'" fill="'+C.paper+'"/>';
    s+=this._stroke([[0,deskY],[2048,deskY-8]],rand,{w:9,r:3,ov:24});
    s+=this._stroke([[0,deskY+60],[2048,deskY+52]],rand,{w:7,r:3,ov:24});
    s+=this._stroke([[240,deskY+60],[232,1152]],rand,{w:8,r:3}) + this._stroke([[286,deskY+60],[292,1152]],rand,{w:8,r:3});
    s+=this._stroke([[1700,deskY+56],[1692,1152]],rand,{w:8,r:3}) + this._stroke([[1746,deskY+56],[1752,1152]],rand,{w:8,r:3});
    // left outer third: lamp, then monitor
    s+=this.lamp(rand,44,deskY-4,lampOn);
    s+=this.monitorFront(rand,160,664,214,176,null);
    // desk objects, right of centre but below the safe band
    var stackX = mode==='dawn' ? 1444 : 1508;
    s+=this.paperStack(rand,stackX,deskY-6,146,mode==='midday'?5:3);
    s+=this.mugFront(rand,mode==='late'?1286:1332,deskY-58,0.62);
    if(mode==='midday') s+=this._stroke([[470,deskY+26],[604,deskY+18],[610,deskY+36],[476,deskY+44]],rand,{w:5,r:2.4,close:true});
    return s; };

  /* ── the cut: ink-wipe, full frame, one-shot ───────────────────────────
     marker mechanism: one broad chisel sweep laid across the frame, then
     pulled off the same way. Frame 1 clear, midpoint solid, last frame clear. */
  P.inkWipe = function(rand,f,total){
    total=total||9; var mid=(total-1)/2, cov = f<=mid ? f/mid : (total-1-f)/mid, laying = f<=mid;
    if(cov<=0.001) return '';
    var m=this.pen.name;
    if(m==='ballpoint') return this._wipeScribble(rand,cov,laying);
    if(m==='grease')    return this._wipeSmear(rand,cov,laying);
    if(m==='cutpaper')  return this._wipeSlide(rand,cov,laying);
    return this._wipeSweep(rand,cov,laying); };

  /* marker: one broad chisel sweep laid on, then pulled off the same way */
  P._wipeSweep = function(rand,cov,laying){
    var W=1080, H=1920, s='', i, span=W+300,
        edgeX = laying ? -150+cov*span : (1-cov)*span-150,
        x0 = laying ? -150 : edgeX, x1 = laying ? edgeX : W+150,
        wid = Math.max(1,x1-x0), edge=[];
    for(i=0;i<=14;i++) edge.push([ (laying?x1:x0)+(rand()*2-1)*30, -70+i*(H+140)/14 ]);
    var poly = laying ? [[x0,-70]].concat(edge).concat([[x0,H+70]])
                      : edge.concat([[x1,H+70],[x1,-70]]);
    s+=this._p(this.rpath(poly,rand,7)+'Z',{f:this.pen.ink,s:'none',w:0});
    var n=Math.max(2,Math.round(wid/86));
    for(i=0;i<n;i++){ var bx=x0+(i+0.5)*wid/n;
      s+=this._stroke([[bx+(rand()*2-1)*12,-50],[bx+(rand()*2-1)*26,H+50]],rand,{w:3.6,r:6,s:C.paper,op:0.15}); }
    var ex = laying ? x1 : x0, dir = laying ? 1 : -1;
    for(i=0;i<5;i++){ var ey=110+rand()*(H-220), L=44+rand()*156;
      s+=this._stroke([[ex,ey],[ex+dir*L,ey+(rand()*2-1)*28]],rand,{w:6+rand()*10,r:3.4,op:0.82}); }
    return s; };

  /* ballpoint: scribbled loops, tightening as they fill — the pen never lifts */
  P._wipeScribble = function(rand,cov,laying){
    var W=1080, H=1920, s='', i, k, ink=this.pen.ink,
        top = laying ? -40 : (1-cov)*(H+80)-40, bot = laying ? cov*(H+80)-40 : H+40,
        bh = 58, n = Math.max(1,Math.ceil((bot-top)/bh));
    for(i=0;i<n;i++){
      var y = top+(i+0.5)*(bot-top)/n, amp = 26+rand()*10, pts=[], seg=15;
      for(k=0;k<=seg;k++){ var t=k/seg;
        pts.push([ -60+t*(W+120), y+(k%2?amp:-amp)+(rand()*2-1)*7 ]); }
      s+=this._p(this.rpath(pts,rand,5),{s:ink,w:27,op:0.9,cap:'round'});
      s+=this._p(this.rpath(pts.slice().reverse(),rand,7),{s:ink,w:17,op:0.7,cap:'round'});
    }
    return s; };

  /* grease pencil: a sideways smear, the edge crumbling into grain */
  P._wipeSmear = function(rand,cov,laying){
    var W=1080, H=1920, s='', i, ink=this.pen.ink, rows=34, span=W+260;
    for(i=0;i<rows;i++){
      var y=-30+(i+0.5)*(H+60)/rows, L=(laying?cov:1-cov)*span-130+(rand()*2-1)*74,
          x0 = laying ? -70 : L, x1 = laying ? L : W+70;
      if(x1-x0<6) continue;
      s+=this._p(this.rpath([[x0,y],[ (x0+x1)/2, y+(rand()*2-1)*8 ],[x1,y]],rand,4),{s:ink,w:74,op:0.8+rand()*0.14,cap:'butt'});
      var gx = laying ? x1 : x0, d = laying ? 1 : -1, g;
      for(g=0;g<3;g++) s+=this._p(this.rpath([[gx+d*(8+rand()*40),y+(rand()*2-1)*20],[gx+d*(30+rand()*90),y+(rand()*2-1)*24]],rand,5),{s:ink,w:12+rand()*22,op:0.34+rand()*0.3,cap:'butt'});
    }
    return s; };

  /* cut paper: one torn sheet slides across, then off, over the one behind */
  P._wipeSlide = function(rand,cov,laying){
    var W=1080, H=1920, s='', i, span=W+300,
        L = laying ? -150+cov*span : (1-cov)*span-150,
        x0 = laying ? -150 : L, x1 = laying ? L : W+150, tear=[];
    for(i=0;i<=22;i++) tear.push([ (laying?x1:x0)+(rand()*2-1)*26, -70+i*(H+140)/22 ]);
    var poly = laying ? [[x0,-70]].concat(tear).concat([[x0,H+70]])
                      : tear.concat([[x1,H+70],[x1,-70]]);
    var d=this.rpath(poly,rand,4)+'Z';
    s+=this._p(this._shiftPath(poly,14,18,rand),{f:'#cdc9be',s:'none',w:0});
    s+=this._p(d,{f:this.pen.ink,s:'none',w:0});
    var ex = laying ? x1 : x0;
    for(i=0;i<14;i++){ var ey=-40+rand()*(H+80);
      s+=this._p(this.rpath([[ex+(rand()*2-1)*16,ey],[ex+(rand()*2-1)*22,ey+18+rand()*40]],rand,3),{s:'#f2f2ef',w:5,op:0.5,cap:'butt'}); }
    return s; };
  P._shiftPath = function(poly,dx,dy,rand){ return this.rpath(poly.map(function(p){ return [p[0]+dx,p[1]+dy]; }),rand,4)+'Z'; };

  /* ── the additions: framing, emphasis and direction ──────────────────── */
  P.bracketPair = function(rand){ var W=1200, H=700, t=90;
    var s=this._stroke([[t+150,60],[t,60],[t,H-60],[t+150,H-60]],rand,{w:9,r:3.2});
    s+=this._stroke([[W-t-150,60],[W-t,60],[W-t,H-60],[W-t-150,H-60]],rand,{w:9,r:3.2});
    s+=this.pin(rand,t,34,1.2);
    s+=this.slot('interior',t+46,100,W-2*t-92,H-200);
    return s; };
  P.calloutBurst = function(rand){ var cx=450, cy=350, n=13, pts=[], i;
    for(i=0;i<n*2;i++){ var a=Math.PI*2*i/(n*2), rr=(i%2?300:396)*(0.93+rand()*0.15);
      pts.push([cx+rr*Math.cos(a)*1.06, cy+rr*Math.sin(a)*0.82]); }
    pts.push([pts[0][0],pts[0][1]]);
    var s=this._stroke(pts,rand,{w:7,r:2.6});
    s+=this.slot('interior',cx-250,cy-146,500,292);
    return s; };
  P.arrowTrend = function(rand,dir){ var W=800, H=600, y0 = dir>0 ? H-110 : 110;
    var p3=[700, dir>0 ? 110 : H-110], p2=[470, y0-dir*70];
    var s=this._stroke([[70,y0],[280,y0-dir*118],p2,p3],rand,{w:11,r:3.4});
    s+=this._head2(p3[0],p3[1],Math.atan2(p3[1]-p2[1],p3[0]-p2[0]),76,rand,{w:10,r:3});
    s+=this._stroke([[54,H-40],[W-46,H-42]],rand,{w:5,r:2.6,s:C.grey,op:0.6,ov:8});
    return s; };
  P.underlineSwipe = function(rand,f,total){ var W=1000, H=220, t=(f+1)/total, x1=60+(W-120)*t;
    var s=this._stroke([[60,H*0.58],[60+(x1-60)*0.5,H*0.5],[x1,H*0.62]],rand,{w:15,r:3.6});
    if(t>0.5) s+=this._stroke([[74,H*0.8],[Math.max(96,x1-130),H*0.82]],rand,{w:7,r:3,op:0.55});
    return s; };

  /* ── asset registry ───────────────────────────────────────────────── */
  var ROOM = { x:0, y:0, w:1080, h:1920 }, HOST = { x:280, y:90, w:720, h:900 };
  var A = {};
  function reg(key, o){ A[key]=o; }

  reg('room-wide--marker',          { concept:'room-wide',          group:'A', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:11, kw:1.467, draw:function(i,r,f){ return i.roomWide(r); } });
  reg('room-side--marker',          { concept:'room-side',          group:'A', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:12, kw:1.467, draw:function(i,r,f){ return i.roomSide(r); } });
  reg('room-over-shoulder--marker', { concept:'room-over-shoulder', group:'A', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:13, kw:1.467, draw:function(i,r,f){ return i.roomOver(r); } });
  reg('desk-top-down--marker',      { concept:'desk-top-down',      group:'A', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:14, kw:1.467, draw:function(i,r,f){ return i.deskTop(r); } });
  reg('at-the-sheet--marker',       { concept:'at-the-sheet',       group:'A', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:15, kw:1.467, draw:function(i,r,f){ return i.atSheet(r); } });

  [['talking-to-camera',21,6],['talking-at-screen',22,5],['pointing-at-sheet',23,5],['sitting-with-mug',24,4]].forEach(function(h){
    reg(h[0]+'--marker', { concept:h[0], group:'B', src:HOST, canvas:[720,900], deliver:[1440,1800], seed:h[1], kw:1.167, frames:h[2], playback:'loop',
      draw:function(i,r,f){ return i.host(r,h[0],f); }, frameSeed:function(f){ return h[1]*7919+f*331; } });
    reg(h[0]+'--closed--marker', { concept:h[0]+'--closed', group:'B', src:HOST, canvas:[720,900], deliver:[1440,1800], seed:h[1]+100, kw:1.167,
      draw:function(i,r,f){ return i.hostClosed(r,h[0]); } });
  });

  reg('page-corporate--marker',     { concept:'page-corporate',     group:'C', src:{x:0,y:0,w:1000,h:1300}, canvas:[1080,1440], deliver:[2160,2880], seed:31, kw:1.467, draw:function(i,r){ return i.pageCorporate(r); } });
  reg('page-institutional--marker', { concept:'page-institutional', group:'C', src:{x:0,y:0,w:1000,h:1300}, canvas:[1080,1440], deliver:[2160,2880], seed:32, kw:1.467, draw:function(i,r){ return i.pageInstitutional(r); } });
  reg('sheet-frame--marker',        { concept:'sheet-frame',        group:'C', src:{x:0,y:0,w:1400,h:900},  canvas:[1440,960],  deliver:[2880,1920], seed:33, kw:1.767, draw:function(i,r){ return i.sheetFrame(r) + i.clip(r,700,-8,1.7); } });
  reg('monitor--marker',            { concept:'monitor',            group:'C', src:{x:0,y:0,w:1600,h:1000}, canvas:[1440,900],  deliver:[2880,1800], seed:34, kw:1.767, draw:function(i,r){ return i.monitorProp(r) + i.blot(r,1524,958,11); } });
  reg('stamp--marker',              { concept:'stamp',              group:'C', src:{x:0,y:0,w:800,h:500},   canvas:[720,480],   deliver:[1440,960],  seed:35, kw:1.167, draw:function(i,r){ return i.stampProp(r); } });
  reg('card-guidance--marker',      { concept:'card-guidance',      group:'C', src:{x:0,y:0,w:700,h:460},   canvas:[720,480],   deliver:[1440,960],  seed:36, kw:1.167, draw:function(i,r){ return i.cardGuidance(r) + i.paperclip(r,38,-20,1.05); } });
  reg('chain-of-three--marker',     { concept:'chain-of-three',     group:'C', src:{x:0,y:0,w:1800,h:700},  canvas:[1440,720],  deliver:[2880,1440], seed:37, kw:1.767, draw:function(i,r){ return i.chainOfThree(r) + i.pin(r,30,26,1.45); } });
  reg('card-consequence--marker',   { concept:'card-consequence',   group:'C', src:{x:0,y:0,w:520,h:620},   canvas:[480,720],   deliver:[960,1440],  seed:38, kw:1.0,   draw:function(i,r){ return i.cardConsequence(r); } });
  reg('card-consequence-b--marker', { concept:'card-consequence-b', group:'C', src:{x:0,y:0,w:520,h:620},   canvas:[480,720],   deliver:[960,1440],  seed:40, kw:1.0,   draw:function(i,r){ return i.cardConsequenceB(r); } });
  reg('compare-plate--marker',      { concept:'compare-plate',      group:'C', src:{x:0,y:0,w:1600,h:700},  canvas:[1440,720],  deliver:[2880,1440], seed:39, kw:1.767, draw:function(i,r){ return i.comparePlate(r) + i.foldCorner(r,1598,698,1.45,1); } });

  reg('bracket-pair--marker',       { concept:'bracket-pair',       group:'C', src:{x:0,y:0,w:1200,h:700},  canvas:[1440,840],  deliver:[2880,1680], seed:81, kw:1.6,   draw:function(i,r){ return i.bracketPair(r); } });
  reg('callout-burst--marker',      { concept:'callout-burst',      group:'C', src:{x:0,y:0,w:900,h:700},   canvas:[1080,840],  deliver:[2160,1680], seed:82, kw:1.3,   draw:function(i,r){ return i.calloutBurst(r); } });
  reg('arrow-rising--marker',       { concept:'arrow-rising',       group:'C', src:{x:0,y:0,w:800,h:600},   canvas:[900,675],   deliver:[1800,1350], seed:83, kw:1.2,   draw:function(i,r){ return i.arrowTrend(r,1); } });
  reg('arrow-falling--marker',      { concept:'arrow-falling',      group:'C', src:{x:0,y:0,w:800,h:600},   canvas:[900,675],   deliver:[1800,1350], seed:84, kw:1.2,   draw:function(i,r){ return i.arrowTrend(r,-1); } });

  var AV = { x:370, y:140, w:260, h:292 };
  reg('sheet-tall--marker',  { concept:'sheet-tall',  group:'D', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:61, kw:1.467, draw:function(i,r){ return i.sheetTall(r); } });
  reg('screen-full--marker', { concept:'screen-full', group:'D', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:62, kw:1.467, draw:function(i,r){ return i.screenFull(r); } });
  reg('number-full--marker', { concept:'number-full', group:'D', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:63, kw:1.467, draw:function(i,r){ return i.numberFull(r); } });
  [['flat',41],['unimpressed',42],['mid-blink',43],['brow-raised',44]].forEach(function(v){
    reg('avatar-'+v[0]+'--marker', { concept:'avatar-'+v[0], group:'ID', src:AV, canvas:[800,800], deliver:[800,800], seed:v[1], kw:1.0, bg:C.paper, pad:78,
      draw:function(i,r){ return i.avatarFace(r,v[0]); } });
  });
  [['3am',51],['dawn',52],['midday',53],['late',54]].forEach(function(b){
    reg('channel-banner-'+b[0]+'--marker', { concept:'channel-banner-'+b[0], group:'ID', src:{x:0,y:0,w:2048,h:1152}, canvas:[2048,1152], deliver:[2048,1152], seed:b[1], kw:1.3, bg:C.paper,
      draw:function(i,r){ return i.banner(r,b[0]); } });
    reg('channel-banner-'+b[0]+'--safe--marker', { concept:'channel-banner-'+b[0]+'--safe', group:'ID', src:{x:0,y:0,w:2048,h:1152}, canvas:[2048,1152], deliver:[2048,1152], seed:b[1], kw:1.3, bg:C.paper, overlay:'safe',
      draw:function(i,r){ return i.banner(r,b[0]); } });
  });

  reg('ink-wipe--marker', { concept:'ink-wipe', group:'E', src:ROOM, canvas:[1080,1920], deliver:[2160,3840], seed:71, kw:1.467, frames:9, playback:'one-shot',
    draw:function(i,r,f){ return i.inkWipe(r,f,9); }, frameSeed:function(f){ return 71*7919+f*331; } });
  reg('underline-swipe--marker', { concept:'underline-swipe', group:'E', src:{x:0,y:0,w:1000,h:220}, canvas:[1080,240], deliver:[2160,480], seed:85, kw:1.2, frames:4, playback:'one-shot',
    draw:function(i,r,f){ return i.underlineSwipe(r,f,4); }, frameSeed:function(f){ return 85*7919+f*331; } });

  /* the other three registers: same geometry, same slots, different instrument.
     Group ID is not cloned — the channel has one identity, not four. */
  var REGS = [['ballpoint','ballpoint',1000],['grease-pencil','grease',2000],['cut-paper','cutpaper',3000]];
  REGS.forEach(function(rg){
    Object.keys(A).forEach(function(key){
      var a=A[key]; if(a.group==='ID' || a.pen) return;
      var o={}; Object.keys(a).forEach(function(p){ o[p]=a[p]; });
      o.pen = rg[1]; o.seed = a.seed + rg[2];
      if(a.frameSeed){ var sd=o.seed; o.frameSeed=function(f){ return sd*7919+f*331; }; }
      A[key.replace(/--marker$/,'--'+rg[0])] = o;
    });
  });

  /* ── render ───────────────────────────────────────────────────────── */
  /* boil the whole registry: anything static becomes 3 redrawn frames at 7fps.
     Frame-based assets (the wipe, the dive, the host loops) already move and are
     left alone. Nothing about slots changes — geometry is identical per frame. */
  function boilAll(){
    Object.keys(A).forEach(function(key){
      var a = A[key];
      if(a.frames || a.frameSeed) return;
      a.frames = 3; a.fps = 7; a.playback = 'boil'; a.boil = true;
    });
  }

  function render(key, frame, opts){
    opts = opts || {}; frame = frame || 0;
    var a = A[key]; if(!a) throw new Error('unknown asset '+key);
    var cw = a.canvas[0], ch = a.canvas[1], pad = (a.pad||0)*2;
    var k = Math.min((cw-pad)/a.src.w, (ch-pad)/a.src.h);
    var dx = (cw - a.src.w*k)/2 - a.src.x*k, dy = (ch - a.src.h*k)/2 - a.src.y*k;
    var ink = new Ink(a.kw||1, a.pen); ink.guides = !!opts.guides;
    if(a.boil && frame > 0) ink.boil = 1 + frame*0.025;
    var seed = a.frameSeed ? a.frameSeed(frame)
      : a.boil ? a.seed + frame*9176
      : a.seed;
    var inner = a.draw(ink, prng(seed), frame);
    var body = '<g transform="translate('+dx.toFixed(2)+','+dy.toFixed(2)+') scale('+k.toFixed(4)+')">'+inner+'</g>';
    if(a.overlay==='safe'){
      var sx=(2048-1235)/2, sy=(1152-338)/2;
      body += '<g><rect x="'+sx+'" y="'+sy+'" width="1235" height="338" fill="none" stroke="'+C.red+'" stroke-width="6" stroke-dasharray="26 18"/>'
        + '<text x="'+(sx+14)+'" y="'+(sy-18)+'" fill="'+C.red+'" font-family="monospace" font-size="26" font-weight="700">SAFE AREA 1235 × 338</text></g>';
    }
    var slots = ink.slots.map(function(s){ return { name:s.name,
      x:Math.round(dx + s.x*k), y:Math.round(dy + s.y*k),
      w:Math.round(s.w*k), h:Math.round(s.h*k) }; });
    return { inner:body, slots:slots, canvas:[cw,ch], deliver:a.deliver, bg:a.bg||null, group:a.group, concept:a.concept, register:(a.pen||'marker'), frames:a.frames||1, playback:a.playback||'static' };
  }

  function svgFor(key, frame, opts){
    var r = render(key, frame, opts), W = r.deliver[0], H = r.deliver[1];
    return '<svg xmlns="http://www.w3.org/2000/svg" width="'+W+'" height="'+H+'" viewBox="0 0 '+r.canvas[0]+' '+r.canvas[1]+'">'
      + (r.bg ? '<rect x="0" y="0" width="'+r.canvas[0]+'" height="'+r.canvas[1]+'" fill="'+r.bg+'"/>' : '')
      + r.inner + '</svg>';
  }

  function manifest(){
    var out = { registers:['marker','ballpoint','grease-pencil','cut-paper'], palette:{ paper:C.paper, card:'#faf9f6', cardLine:'#e2dfd5', ink:C.ink, inkBallpoint:'#2b3242', inkGrease:'#2a2724', cutShadow:'#cdc9be', muted:C.grey, red:C.red, green:'#2fd576' },
      note:'Slots are x/y/w/h in the asset\u2019s own canvas coordinates, origin top-left. Multiply by delivered/canvas to reach pixels. No text or data is drawn in any asset. Light falls from the upper left in every viewpoint; shadows run down and to the right. sheet-tall returns row-1..row-6 band rectangles inside its interior so code can light one row and ghost the rest. ink-wipe is the cut between shots: 9 numbered frames, one-shot, frame 1 clear, frame 5 solid, frame 9 clear — no slots. The five viewpoints carry a wall/floor junction, a baseboard and one light source (a window off frame-left in room-wide and room-side; its light read as rays elsewhere); overhead desk-top-down has no wall, so it carries the rays only. Slot names and x/y/w/h are identical across all four registers — only the mark-making differs, so a register can be swapped with no recalculation. Group ID (avatars, banners) exists once, in marker: the channel has one identity.',
      fps:12, assets:[] };
    Object.keys(A).forEach(function(key){
      var a=A[key], r=render(key,0);
      var files = a.frames ? [] : [key+'.png'];
      if(a.frames){ for(var f=0;f<a.frames;f++){ files.push(key+'_f'+String(f+1).padStart(2,'0')+'.png'); } }
      out.assets.push({ key:key, concept:a.concept, group:a.group, register:(a.pen==='grease'?'grease-pencil':a.pen==='cutpaper'?'cut-paper':(a.pen||'marker')),
        canvas:{ w:r.canvas[0], h:r.canvas[1] }, delivered:{ w:a.deliver[0], h:a.deliver[1] },
        background: a.bg ? 'paper '+a.bg : 'transparent',
        frames: a.frames || 1, fps: a.fps || 12, playback: a.playback || 'static', files: files, slots: r.slots });
    });
    return out;
  }

  var API = { C:C, prng:prng, Ink:Ink, ASSETS:A, keys:function(){ return Object.keys(A); }, render:render, svgFor:svgFor, manifest:manifest, boilAll:boilAll };
  global.DennisInk = API;
  if (typeof module !== 'undefined') module.exports = API;

})(typeof window !== 'undefined' ? window : globalThis);
