module.exports=[47598,a=>{"use strict";var b=a.i(630825),c=a.i(337366),d=a.i(380560),e=a.i(334603);a.i(975930);var f=a.i(671731),g=a.i(864525),h=function(){var a=(0,e.__name)(function(a,b,c,d){for(c=c||{},d=a.length;d--;c[a[d]]=b);return c},"o"),b=[6,8,10,11,12,14,16,17,18],c=[1,9],d=[1,10],f=[1,11],g=[1,12],h=[1,13],i=[1,14],j={trace:(0,e.__name)(function(){},"trace"),yy:{},symbols_:{error:2,start:3,journey:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NEWLINE:10,title:11,acc_title:12,acc_title_value:13,acc_descr:14,acc_descr_value:15,acc_descr_multiline_value:16,section:17,taskName:18,taskData:19,$accept:0,$end:1},terminals_:{2:"error",4:"journey",6:"EOF",8:"SPACE",10:"NEWLINE",11:"title",12:"acc_title",13:"acc_title_value",14:"acc_descr",15:"acc_descr_value",16:"acc_descr_multiline_value",17:"section",18:"taskName",19:"taskData"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,2]],performAction:(0,e.__name)(function(a,b,c,d,e,f,g){var h=f.length-1;switch(e){case 1:return f[h-1];case 2:case 6:case 7:this.$=[];break;case 3:f[h-1].push(f[h]),this.$=f[h-1];break;case 4:case 5:this.$=f[h];break;case 8:d.setDiagramTitle(f[h].substr(6)),this.$=f[h].substr(6);break;case 9:this.$=f[h].trim(),d.setAccTitle(this.$);break;case 10:case 11:this.$=f[h].trim(),d.setAccDescription(this.$);break;case 12:d.addSection(f[h].substr(8)),this.$=f[h].substr(8);break;case 13:d.addTask(f[h-1],f[h]),this.$="task"}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},a(b,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:c,12:d,14:f,16:g,17:h,18:i},a(b,[2,7],{1:[2,1]}),a(b,[2,3]),{9:15,11:c,12:d,14:f,16:g,17:h,18:i},a(b,[2,5]),a(b,[2,6]),a(b,[2,8]),{13:[1,16]},{15:[1,17]},a(b,[2,11]),a(b,[2,12]),{19:[1,18]},a(b,[2,4]),a(b,[2,9]),a(b,[2,10]),a(b,[2,13])],defaultActions:{},parseError:(0,e.__name)(function(a,b){if(b.recoverable)this.trace(a);else{var c=Error(a);throw c.hash=b,c}},"parseError"),parse:(0,e.__name)(function(a){var b=this,c=[0],d=[],f=[null],g=[],h=this.table,i="",j=0,k=0,l=0,m=g.slice.call(arguments,1),n=Object.create(this.lexer),o={};for(var p in this.yy)Object.prototype.hasOwnProperty.call(this.yy,p)&&(o[p]=this.yy[p]);n.setInput(a,o),o.lexer=n,o.parser=this,void 0===n.yylloc&&(n.yylloc={});var q=n.yylloc;g.push(q);var r=n.options&&n.options.ranges;function s(){var a;return"number"!=typeof(a=d.pop()||n.lex()||1)&&(a instanceof Array&&(a=(d=a).pop()),a=b.symbols_[a]||a),a}"function"==typeof o.parseError?this.parseError=o.parseError:this.parseError=Object.getPrototypeOf(this).parseError,(0,e.__name)(function(a){c.length=c.length-2*a,f.length=f.length-a,g.length=g.length-a},"popStack"),(0,e.__name)(s,"lex");for(var t,u,v,w,x,y,z,A,B,C={};;){if(v=c[c.length-1],this.defaultActions[v]?w=this.defaultActions[v]:(null==t&&(t=s()),w=h[v]&&h[v][t]),void 0===w||!w.length||!w[0]){var D="";for(y in B=[],h[v])this.terminals_[y]&&y>2&&B.push("'"+this.terminals_[y]+"'");D=n.showPosition?"Parse error on line "+(j+1)+":\n"+n.showPosition()+"\nExpecting "+B.join(", ")+", got '"+(this.terminals_[t]||t)+"'":"Parse error on line "+(j+1)+": Unexpected "+(1==t?"end of input":"'"+(this.terminals_[t]||t)+"'"),this.parseError(D,{text:n.match,token:this.terminals_[t]||t,line:n.yylineno,loc:q,expected:B})}if(w[0]instanceof Array&&w.length>1)throw Error("Parse Error: multiple actions possible at state: "+v+", token: "+t);switch(w[0]){case 1:c.push(t),f.push(n.yytext),g.push(n.yylloc),c.push(w[1]),t=null,u?(t=u,u=null):(k=n.yyleng,i=n.yytext,j=n.yylineno,q=n.yylloc,l>0&&l--);break;case 2:if(z=this.productions_[w[1]][1],C.$=f[f.length-z],C._$={first_line:g[g.length-(z||1)].first_line,last_line:g[g.length-1].last_line,first_column:g[g.length-(z||1)].first_column,last_column:g[g.length-1].last_column},r&&(C._$.range=[g[g.length-(z||1)].range[0],g[g.length-1].range[1]]),void 0!==(x=this.performAction.apply(C,[i,k,j,o,w[1],f,g].concat(m))))return x;z&&(c=c.slice(0,-1*z*2),f=f.slice(0,-1*z),g=g.slice(0,-1*z)),c.push(this.productions_[w[1]][0]),f.push(C.$),g.push(C._$),A=h[c[c.length-2]][c[c.length-1]],c.push(A);break;case 3:return!0}}return!0},"parse")};function k(){this.yy={}}return j.lexer={EOF:1,parseError:(0,e.__name)(function(a,b){if(this.yy.parser)this.yy.parser.parseError(a,b);else throw Error(a)},"parseError"),setInput:(0,e.__name)(function(a,b){return this.yy=b||this.yy||{},this._input=a,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:(0,e.__name)(function(){var a=this._input[0];return this.yytext+=a,this.yyleng++,this.offset++,this.match+=a,this.matched+=a,a.match(/(?:\r\n?|\n).*/g)?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),a},"input"),unput:(0,e.__name)(function(a){var b=a.length,c=a.split(/(?:\r\n?|\n)/g);this._input=a+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-b),this.offset-=b;var d=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),c.length-1&&(this.yylineno-=c.length-1);var e=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:c?(c.length===d.length?this.yylloc.first_column:0)+d[d.length-c.length].length-c[0].length:this.yylloc.first_column-b},this.options.ranges&&(this.yylloc.range=[e[0],e[0]+this.yyleng-b]),this.yyleng=this.yytext.length,this},"unput"),more:(0,e.__name)(function(){return this._more=!0,this},"more"),reject:(0,e.__name)(function(){return this.options.backtrack_lexer?(this._backtrack=!0,this):this.parseError("Lexical error on line "+(this.yylineno+1)+". You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).\n"+this.showPosition(),{text:"",token:null,line:this.yylineno})},"reject"),less:(0,e.__name)(function(a){this.unput(this.match.slice(a))},"less"),pastInput:(0,e.__name)(function(){var a=this.matched.substr(0,this.matched.length-this.match.length);return(a.length>20?"...":"")+a.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:(0,e.__name)(function(){var a=this.match;return a.length<20&&(a+=this._input.substr(0,20-a.length)),(a.substr(0,20)+(a.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:(0,e.__name)(function(){var a=this.pastInput(),b=Array(a.length+1).join("-");return a+this.upcomingInput()+"\n"+b+"^"},"showPosition"),test_match:(0,e.__name)(function(a,b){var c,d,e;if(this.options.backtrack_lexer&&(e={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(e.yylloc.range=this.yylloc.range.slice(0))),(d=a[0].match(/(?:\r\n?|\n).*/g))&&(this.yylineno+=d.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:d?d[d.length-1].length-d[d.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+a[0].length},this.yytext+=a[0],this.match+=a[0],this.matches=a,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(a[0].length),this.matched+=a[0],c=this.performAction.call(this,this.yy,this,b,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),c)return c;if(this._backtrack)for(var f in e)this[f]=e[f];return!1},"test_match"),next:(0,e.__name)(function(){if(this.done)return this.EOF;this._input||(this.done=!0),this._more||(this.yytext="",this.match="");for(var a,b,c,d,e=this._currentRules(),f=0;f<e.length;f++)if((c=this._input.match(this.rules[e[f]]))&&(!b||c[0].length>b[0].length)){if(b=c,d=f,this.options.backtrack_lexer){if(!1!==(a=this.test_match(c,e[f])))return a;if(!this._backtrack)return!1;b=!1;continue}if(!this.options.flex)break}return b?!1!==(a=this.test_match(b,e[d]))&&a:""===this._input?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+". Unrecognized text.\n"+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:(0,e.__name)(function(){var a=this.next();return a||this.lex()},"lex"),begin:(0,e.__name)(function(a){this.conditionStack.push(a)},"begin"),popState:(0,e.__name)(function(){return this.conditionStack.length-1>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:(0,e.__name)(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:(0,e.__name)(function(a){return(a=this.conditionStack.length-1-Math.abs(a||0))>=0?this.conditionStack[a]:"INITIAL"},"topState"),pushState:(0,e.__name)(function(a){this.begin(a)},"pushState"),stateStackSize:(0,e.__name)(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:(0,e.__name)(function(a,b,c,d){switch(c){case 0:case 1:case 3:case 4:break;case 2:return 10;case 5:return 4;case 6:return 11;case 7:return this.begin("acc_title"),12;case 8:return this.popState(),"acc_title_value";case 9:return this.begin("acc_descr"),14;case 10:return this.popState(),"acc_descr_value";case 11:this.begin("acc_descr_multiline");break;case 12:this.popState();break;case 13:return"acc_descr_multiline_value";case 14:return 17;case 15:return 18;case 16:return 19;case 17:return":";case 18:return 6;case 19:return"INVALID"}},"anonymous"),rules:[/^(?:%(?!\{)[^\n]*)/i,/^(?:[^\}]%%[^\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:#[^\n]*)/i,/^(?:journey\b)/i,/^(?:title\s[^#\n;]+)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:section\s[^#:\n;]+)/i,/^(?:[^#:\n;]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[12,13],inclusive:!1},acc_descr:{rules:[10],inclusive:!1},acc_title:{rules:[8],inclusive:!1},INITIAL:{rules:[0,1,2,3,4,5,6,7,9,11,14,15,16,17,18,19],inclusive:!0}}},(0,e.__name)(k,"Parser"),k.prototype=j,j.Parser=k,new k}();h.parser=h;var i="",j=[],k=[],l=[],m=(0,e.__name)(function(){j.length=0,k.length=0,i="",l.length=0,(0,d.clear)()},"clear"),n=(0,e.__name)(function(a){i=a,j.push(a)},"addSection"),o=(0,e.__name)(function(){return j},"getSections"),p=(0,e.__name)(function(){let a=t(),b=0;for(;!a&&b<100;)a=t(),b++;return k.push(...l),k},"getTasks"),q=(0,e.__name)(function(){let a=[];return k.forEach(b=>{b.people&&a.push(...b.people)}),[...new Set(a)].sort()},"updateActors"),r=(0,e.__name)(function(a,b){let c=b.substr(1).split(":"),d=0,e=[];1===c.length?(d=Number(c[0]),e=[]):(d=Number(c[0]),e=c[1].split(","));let f=e.map(a=>a.trim()),g={section:i,type:i,people:f,task:a,score:d};l.push(g)},"addTask"),s=(0,e.__name)(function(a){let b={section:i,type:i,description:a,task:a,classes:[]};k.push(b)},"addTaskOrg"),t=(0,e.__name)(function(){let a=(0,e.__name)(function(a){return l[a].processed},"compileTask"),b=!0;for(let[c,d]of l.entries())a(c),b=b&&d.processed;return b},"compileTasks"),u=(0,e.__name)(function(){return q()},"getActors"),v={getConfig:(0,e.__name)(()=>(0,d.getConfig2)().journey,"getConfig"),clear:m,setDiagramTitle:d.setDiagramTitle,getDiagramTitle:d.getDiagramTitle,setAccTitle:d.setAccTitle,getAccTitle:d.getAccTitle,setAccDescription:d.setAccDescription,getAccDescription:d.getAccDescription,addSection:n,getSections:o,getTasks:p,addTask:r,addTaskOrg:s,getActors:u},w=(0,e.__name)(a=>`.label {
    font-family: ${a.fontFamily};
    color: ${a.textColor};
  }
  .mouth {
    stroke: #666;
  }

  line {
    stroke: ${a.textColor}
  }

  .legend {
    fill: ${a.textColor};
    font-family: ${a.fontFamily};
  }

  .label text {
    fill: #333;
  }
  .label {
    color: ${a.textColor}
  }

  .face {
    ${a.faceColor?`fill: ${a.faceColor}`:"fill: #FFF8DC"};
    stroke: #999;
  }

  .node rect,
  .node circle,
  .node ellipse,
  .node polygon,
  .node path {
    fill: ${a.mainBkg};
    stroke: ${a.nodeBorder};
    stroke-width: 1px;
  }

  .node .label {
    text-align: center;
  }
  .node.clickable {
    cursor: pointer;
  }

  .arrowheadPath {
    fill: ${a.arrowheadColor};
  }

  .edgePath .path {
    stroke: ${a.lineColor};
    stroke-width: 1.5px;
  }

  .flowchart-link {
    stroke: ${a.lineColor};
    fill: none;
  }

  .edgeLabel {
    background-color: ${a.edgeLabelBackground};
    rect {
      opacity: 0.5;
    }
    text-align: center;
  }

  .cluster rect {
  }

  .cluster text {
    fill: ${a.titleColor};
  }

  div.mermaidTooltip {
    position: absolute;
    text-align: center;
    max-width: 200px;
    padding: 2px;
    font-family: ${a.fontFamily};
    font-size: 12px;
    background: ${a.tertiaryColor};
    border: 1px solid ${a.border2};
    border-radius: 2px;
    pointer-events: none;
    z-index: 100;
  }

  .task-type-0, .section-type-0  {
    ${a.fillType0?`fill: ${a.fillType0}`:""};
  }
  .task-type-1, .section-type-1  {
    ${a.fillType0?`fill: ${a.fillType1}`:""};
  }
  .task-type-2, .section-type-2  {
    ${a.fillType0?`fill: ${a.fillType2}`:""};
  }
  .task-type-3, .section-type-3  {
    ${a.fillType0?`fill: ${a.fillType3}`:""};
  }
  .task-type-4, .section-type-4  {
    ${a.fillType0?`fill: ${a.fillType4}`:""};
  }
  .task-type-5, .section-type-5  {
    ${a.fillType0?`fill: ${a.fillType5}`:""};
  }
  .task-type-6, .section-type-6  {
    ${a.fillType0?`fill: ${a.fillType6}`:""};
  }
  .task-type-7, .section-type-7  {
    ${a.fillType0?`fill: ${a.fillType7}`:""};
  }

  .actor-0 {
    ${a.actor0?`fill: ${a.actor0}`:""};
  }
  .actor-1 {
    ${a.actor1?`fill: ${a.actor1}`:""};
  }
  .actor-2 {
    ${a.actor2?`fill: ${a.actor2}`:""};
  }
  .actor-3 {
    ${a.actor3?`fill: ${a.actor3}`:""};
  }
  .actor-4 {
    ${a.actor4?`fill: ${a.actor4}`:""};
  }
  .actor-5 {
    ${a.actor5?`fill: ${a.actor5}`:""};
  }
  ${(0,b.getIconStyles)()}
`,"getStyles"),x=(0,e.__name)(function(a,b){return(0,c.drawRect)(a,b)},"drawRect"),y=(0,e.__name)(function(a,b){let c=a.append("circle").attr("cx",b.cx).attr("cy",b.cy).attr("class","face").attr("r",15).attr("stroke-width",2).attr("overflow","visible"),d=a.append("g");function f(a){let c=(0,g.arc)().startAngle(Math.PI/2).endAngle(Math.PI/2*3).innerRadius(7.5).outerRadius(15/2.2);a.append("path").attr("class","mouth").attr("d",c).attr("transform","translate("+b.cx+","+(b.cy+2)+")")}function h(a){let c=(0,g.arc)().startAngle(3*Math.PI/2).endAngle(Math.PI/2*5).innerRadius(7.5).outerRadius(15/2.2);a.append("path").attr("class","mouth").attr("d",c).attr("transform","translate("+b.cx+","+(b.cy+7)+")")}function i(a){a.append("line").attr("class","mouth").attr("stroke",2).attr("x1",b.cx-5).attr("y1",b.cy+7).attr("x2",b.cx+5).attr("y2",b.cy+7).attr("class","mouth").attr("stroke-width","1px").attr("stroke","#666")}return d.append("circle").attr("cx",b.cx-5).attr("cy",b.cy-5).attr("r",1.5).attr("stroke-width",2).attr("fill","#666").attr("stroke","#666"),d.append("circle").attr("cx",b.cx+5).attr("cy",b.cy-5).attr("r",1.5).attr("stroke-width",2).attr("fill","#666").attr("stroke","#666"),(0,e.__name)(f,"smile"),(0,e.__name)(h,"sad"),(0,e.__name)(i,"ambivalent"),b.score>3?f(d):b.score<3?h(d):i(d),c},"drawFace"),z=(0,e.__name)(function(a,b){let c=a.append("circle");return c.attr("cx",b.cx),c.attr("cy",b.cy),c.attr("class","actor-"+b.pos),c.attr("fill",b.fill),c.attr("stroke",b.stroke),c.attr("r",b.r),void 0!==c.class&&c.attr("class",c.class),void 0!==b.title&&c.append("title").text(b.title),c},"drawCircle"),A=(0,e.__name)(function(a,b){return(0,c.drawText)(a,b)},"drawText"),B=(0,e.__name)(function(a,b,d){let e=a.append("g"),f=(0,c.getNoteRect)();f.x=b.x,f.y=b.y,f.fill=b.fill,f.width=d.width*b.taskCount+d.diagramMarginX*(b.taskCount-1),f.height=d.height,f.class="journey-section section-type-"+b.num,f.rx=3,f.ry=3,x(e,f),E(d)(b.text,e,f.x,f.y,f.width,f.height,{class:"journey-section section-type-"+b.num},d,b.colour)},"drawSection"),C=-1,D=(0,e.__name)(function(a,b,d,e){let f=b.x+d.width/2,g=a.append("g");C++,g.append("line").attr("id",e+"-task"+C).attr("x1",f).attr("y1",b.y).attr("x2",f).attr("y2",450).attr("class","task-line").attr("stroke-width","1px").attr("stroke-dasharray","4 2").attr("stroke","#666"),y(g,{cx:f,cy:300+(5-b.score)*30,score:b.score});let h=(0,c.getNoteRect)();h.x=b.x,h.y=b.y,h.fill=b.fill,h.width=d.width,h.height=d.height,h.class="task task-type-"+b.num,h.rx=3,h.ry=3,x(g,h);let i=b.x+14;b.people.forEach(a=>{let c=b.actors[a].color;z(g,{cx:i,cy:b.y,r:7,fill:c,stroke:"#000",title:a,pos:b.actors[a].position}),i+=10}),E(d)(b.task,g,h.x,h.y,h.width,h.height,{class:"task"},d,b.colour)},"drawTask"),E=function(){function a(a,b,c,e,f,g,h,i){d(b.append("text").attr("x",c+f/2).attr("y",e+g/2+5).style("font-color",i).style("text-anchor","middle").text(a),h)}function b(a,b,c,e,f,g,h,i,j){let{taskFontSize:k,taskFontFamily:l}=i,m=a.split(/<br\s*\/?>/gi);for(let a=0;a<m.length;a++){let i=a*k-k*(m.length-1)/2,n=b.append("text").attr("x",c+f/2).attr("y",e).attr("fill",j).style("text-anchor","middle").style("font-size",k).style("font-family",l);n.append("tspan").attr("x",c+f/2).attr("dy",i).text(m[a]),n.attr("y",e+g/2).attr("dominant-baseline","central").attr("alignment-baseline","central"),d(n,h)}}function c(a,c,e,f,g,h,i,j){let k=c.append("switch"),l=k.append("foreignObject").attr("x",e).attr("y",f).attr("width",g).attr("height",h).attr("position","fixed").append("xhtml:div").style("display","table").style("height","100%").style("width","100%");l.append("div").attr("class","label").style("display","table-cell").style("text-align","center").style("vertical-align","middle").text(a),b(a,k,e,f,g,h,i,j),d(l,i)}function d(a,b){for(let c in b)c in b&&a.attr(c,b[c])}return(0,e.__name)(a,"byText"),(0,e.__name)(b,"byTspan"),(0,e.__name)(c,"byFo"),(0,e.__name)(d,"_setTextAttrs"),function(d){return"fo"===d.textPlacement?c:"old"===d.textPlacement?a:b}}(),F=(0,e.__name)(function(a,b){C=-1,a.append("defs").append("marker").attr("id",b+"-arrowhead").attr("refX",5).attr("refY",2).attr("markerWidth",6).attr("markerHeight",4).attr("orient","auto").append("path").attr("d","M 0,0 V 4 L6,2 Z")},"initGraphics"),G=(0,e.__name)(function(a){Object.keys(a).forEach(function(b){K[b]=a[b]})},"setConf"),H={},I=0;function J(a){let b=(0,d.getConfig2)().journey,c=b.maxLabelWidth;I=0;let e=60;Object.keys(H).forEach(d=>{let f=H[d].color;z(a,{cx:20,cy:e,r:7,fill:f,stroke:"#000",pos:H[d].position});let g=a.append("text").attr("visibility","hidden").text(d),h=g.node().getBoundingClientRect().width;g.remove();let i=[];if(h<=c)i=[d];else{let b=d.split(" "),e="";g=a.append("text").attr("visibility","hidden"),b.forEach(a=>{let b=e?`${e} ${a}`:a;if(g.text(b),g.node().getBoundingClientRect().width>c){if(e&&i.push(e),e=a,g.text(a),g.node().getBoundingClientRect().width>c){let b="";for(let d of a)b+=d,g.text(b+"-"),g.node().getBoundingClientRect().width>c&&(i.push(b.slice(0,-1)+"-"),b=d);e=b}}else e=b}),e&&i.push(e),g.remove()}i.forEach((c,d)=>{let f=A(a,{x:40,y:e+7+20*d,fill:"#666",text:c,textMargin:b.boxTextMargin??5}).node().getBoundingClientRect().width;f>I&&f>b.leftMargin-f&&(I=f)}),e+=Math.max(20,20*i.length)})}(0,e.__name)(J,"drawActorLegend");var K=(0,d.getConfig2)().journey,L=0,M=(0,e.__name)(function(a,b,c,e){let g,h=(0,d.getConfig2)(),i=h.journey.titleColor,j=h.journey.titleFontSize,k=h.journey.titleFontFamily,l=h.securityLevel;"sandbox"===l&&(g=(0,f.select)("#i"+b));let m="sandbox"===l?(0,f.select)(g.nodes()[0].contentDocument.body):(0,f.select)("body");N.init();let n=m.select("#"+b);F(n,b);let o=e.db.getTasks(),p=e.db.getDiagramTitle(),q=e.db.getActors();for(let a in H)delete H[a];let r=0;q.forEach(a=>{H[a]={color:K.actorColours[r%K.actorColours.length],position:r},r++}),J(n),L=K.leftMargin+I,N.insert(0,0,L,50*Object.keys(H).length),Q(n,o,0,b);let s=N.getBounds();p&&n.append("text").text(p).attr("x",L).attr("font-size",j).attr("font-weight","bold").attr("y",25).attr("fill",i).attr("font-family",k);let t=s.stopy-s.starty+2*K.diagramMarginY,u=L+s.stopx+2*K.diagramMarginX;(0,d.configureSvgSize)(n,t,u,K.useMaxWidth),n.append("line").attr("x1",L).attr("y1",4*K.height).attr("x2",u-L-4).attr("y2",4*K.height).attr("stroke-width",4).attr("stroke","black").attr("marker-end","url(#"+b+"-arrowhead)");let v=70*!!p;n.attr("viewBox",`${s.startx} -25 ${u} ${t+v}`),n.attr("preserveAspectRatio","xMinYMin meet"),n.attr("height",t+v+25)},"draw"),N={data:{startx:void 0,stopx:void 0,starty:void 0,stopy:void 0},verticalPos:0,sequenceItems:[],init:(0,e.__name)(function(){this.sequenceItems=[],this.data={startx:void 0,stopx:void 0,starty:void 0,stopy:void 0},this.verticalPos=0},"init"),updateVal:(0,e.__name)(function(a,b,c,d){void 0===a[b]?a[b]=c:a[b]=d(c,a[b])},"updateVal"),updateBounds:(0,e.__name)(function(a,b,c,f){let g=(0,d.getConfig2)().journey,h=this,i=0;function j(d){return(0,e.__name)(function(e){i++;let j=h.sequenceItems.length-i+1;h.updateVal(e,"starty",b-j*g.boxMargin,Math.min),h.updateVal(e,"stopy",f+j*g.boxMargin,Math.max),h.updateVal(N.data,"startx",a-j*g.boxMargin,Math.min),h.updateVal(N.data,"stopx",c+j*g.boxMargin,Math.max),"activation"!==d&&(h.updateVal(e,"startx",a-j*g.boxMargin,Math.min),h.updateVal(e,"stopx",c+j*g.boxMargin,Math.max),h.updateVal(N.data,"starty",b-j*g.boxMargin,Math.min),h.updateVal(N.data,"stopy",f+j*g.boxMargin,Math.max))},"updateItemBounds")}(0,e.__name)(j,"updateFn"),this.sequenceItems.forEach(j())},"updateBounds"),insert:(0,e.__name)(function(a,b,c,d){let e=Math.min(a,c),f=Math.max(a,c),g=Math.min(b,d),h=Math.max(b,d);this.updateVal(N.data,"startx",e,Math.min),this.updateVal(N.data,"starty",g,Math.min),this.updateVal(N.data,"stopx",f,Math.max),this.updateVal(N.data,"stopy",h,Math.max),this.updateBounds(e,g,f,h)},"insert"),bumpVerticalPos:(0,e.__name)(function(a){this.verticalPos=this.verticalPos+a,this.data.stopy=this.verticalPos},"bumpVerticalPos"),getVerticalPos:(0,e.__name)(function(){return this.verticalPos},"getVerticalPos"),getBounds:(0,e.__name)(function(){return this.data},"getBounds")},O=K.sectionFills,P=K.sectionColours,Q=(0,e.__name)(function(a,b,c,e){let f=(0,d.getConfig2)().journey,g="",h=c+(2*f.height+f.diagramMarginY),i=0,j="#CCC",k="black",l=0;for(let[c,d]of b.entries()){if(g!==d.section){j=O[i%O.length],l=i%O.length,k=P[i%P.length];let e=0,h=d.section;for(let a=c;a<b.length;a++)if(b[a].section==h)e+=1;else break;B(a,{x:c*f.taskMargin+c*f.width+L,y:50,text:d.section,fill:j,num:l,colour:k,taskCount:e},f),g=d.section,i++}let m=d.people.reduce((a,b)=>(H[b]&&(a[b]=H[b]),a),{});d.x=c*f.taskMargin+c*f.width+L,d.y=h,d.width=f.diagramMarginX,d.height=f.diagramMarginY,d.colour=k,d.fill=j,d.num=l,d.actors=m,D(a,d,f,e),N.insert(d.x,d.y,d.x+d.width+f.taskMargin,450)}},"drawTasks"),R={setConf:G,draw:M},S={parser:h,db:v,renderer:R,styles:w,init:(0,e.__name)(a=>{R.setConf(a.journey),v.clear()},"init")};a.s(["diagram",0,S])}];

//# sourceMappingURL=0_lp_modules_mermaid_dist_chunks_mermaid_core_journeyDiagram-VCZTEJTY_mjs_0q7b_tk._.js.map