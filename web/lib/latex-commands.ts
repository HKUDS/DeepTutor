/**
 * KaTeX control-sequence names, extracted from the bundled `katex` build.
 *
 * Used to decide whether a backslash token in prose is a real formula or just
 * a stray escape — `\overline{A+B}` is maths, `C:\Users\frank` is a path. Only
 * names of three characters or more are listed: one- and two-letter control
 * sequences (`\i`, `\to`, `\ne`) are accepted unconditionally because the
 * short list is dominated by them, and a fragment still needs at least one
 * *trigger* command (below) before anything is rewritten.
 *
 * Regenerate with:
 *   node -e 'const s=require("fs").readFileSync("node_modules/katex/dist/katex.mjs","utf8");
 *     const n=new Set();for(const m of s.matchAll(/["'`]\\\\([a-zA-Z]{1,20})["'`]/g))n.add(m[1]);
 *     console.log([...n].filter(x=>x.length>=3).sort().join(" "))'
 */
const KATEX_COMMAND_SOURCE = [
  "Alpha And Bbb Bbbk Beta Big Bigg Biggl Biggm Biggr Bigl Bigm Bigr Box",
  "Bra Braket Bumpeq Cap Chi Colonapprox Coloneq Coloneqq Colonsim Complex",
  "Cup DOTSB DOTSI DOTSX Dagger Darr Delta Diamond Doteq Downarrow Epsilon",
  "Eqcolon Eqqcolon Eta Finv Game Gamma Harr Huge Iota Join KaTeX Kappa Ket",
  "LARGE LaTeX Lambda Large Larr Leftarrow Leftrightarrow Lleftarrow",
  "Longleftarrow Longleftrightarrow Longrightarrow Lrarr Lsh Omega Omicron",
  "Overrightarrow Phi Psi Rarr Reals Relbar Rho Rightarrow Rrightarrow Rsh",
  "Set Sigma Subset Supset Tau TeX TextOrMath Theta Uarr Uparrow",
  "Updownarrow Upsilon Vdash Vert Vvdash Zeta above acute alef alefsym",
  "aleph allowbreak alpha amalg angl angle angln approx approxcolon",
  "approxcoloncolon approxeq arccos arcctg arcsin arctan arctg arg argmax",
  "argmin arraystretch ast asymp atop backepsilon backprime backsim",
  "backsimeq backslash bar barwedge bcancel because begin begingroup beta",
  "beth between bgroup big bigcap bigcirc bigcup bigg biggl biggm biggr",
  "bigl bigm bigodot bigoplus bigotimes bigr bigsqcup bigstar",
  "bigtriangledown bigtriangleup biguplus bigvee bigwedge binom",
  "blacklozenge blacksquare blacktriangle blacktriangledown",
  "blacktriangleleft blacktriangleright blue blueA blueB blueC blueD blueE",
  "bmod bold boldsymbol bot bowtie boxdot boxed boxminus boxplus boxtimes",
  "bra brace brack braket breve bull bullet bumpeq cal cancel cap",
  "cdleftarrow cdlongequal cdot cdotp cdots cdrightarrow centerdot cfrac",
  "char check checkmark chi choose circ circeq circlearrowleft",
  "circlearrowright circledR circledS circledast circledcirc circleddash",
  "clap clubs clubsuit cnums colon colonapprox coloncolon coloncolonapprox",
  "coloncolonequals coloncolonminus coloncolonsim coloneq coloneqq",
  "colonequals colonminus colonsim color colorbox complement cong coprod",
  "copyright cos cosec cosh cot cotg coth csc ctg cth cup curlyeqprec",
  "curlyeqsucc curlyvee curlywedge curvearrowleft curvearrowright dArr dag",
  "dagger daleth darr dashleftarrow dashrightarrow dashv dbinom dblcolon",
  "ddag ddagger ddddot dddot ddot ddots def deg degree delta det dfrac",
  "diagdown diagup diamond diamonds diamondsuit digamma dim displaystyle",
  "div divideontimes dot doteq doteqdot dotplus dots dotsb dotsc dotsi",
  "dotsm dotso dotsx doublebarwedge doublecap doublecup downarrow",
  "downdownarrows downharpoonleft downharpoonright edef egroup ell emph",
  "empty emptyset end endgroup enskip enspace epsilon eqcirc eqcolon",
  "eqqcolon eqsim eqslantgtr eqslantless equalscolon equalscoloncolon equiv",
  "errmessage eta eth exist exists exp expandafter fallingdotseq fbox",
  "fcolorbox flat footnotesize forall frac frak frown futurelet gamma gcd",
  "gdef genfrac geq geqq geqslant gets ggg gggtr gimel global gnapprox gneq",
  "gneqq gnsim goldA goldB goldC goldD goldE grave gray grayA grayB grayC",
  "grayD grayE grayF grayG grayH grayI green greenA greenB greenC greenD",
  "greenE gtrapprox gtrdot gtreqless gtreqqless gtrless gtrsim gvertneqq",
  "hArr harr hat hbar hbox hdashline hearts heartsuit hline hom",
  "hookleftarrow hookrightarrow hphantom href hskip hslash hspace htmlClass",
  "htmlData htmlId htmlStyle huge idotsint iff iiiint iiint iint image",
  "imageof imath impliedby implies includegraphics inf infin infty injlim",
  "int intercal intop iota isin jmath kaBlue kaGreen kappa ker kern ket",
  "lArr lBrace lVert lambda land lang langle large larr lbrace lbrack lceil",
  "ldotp ldots leadsto left leftarrow leftarrowtail leftharpoondown",
  "leftharpoonup leftleftarrows leftrightarrow leftrightarrows",
  "leftrightharpoons leftrightsquigarrow leftthreetimes leq leqq leqslant",
  "lessapprox lessdot lesseqgtr lesseqqgtr lessgtr lesssim let lfloor",
  "lgroup lhd lim liminf limits limsup llap llbracket llcorner lll llless",
  "lmoustache lnapprox lneq lneqq lnot lnsim log long longleftarrow",
  "longleftrightarrow longmapsto longrightarrow looparrowleft",
  "looparrowright lor lozenge lparen lrArr lrarr lrcorner ltimes lvert",
  "lvertneqq maltese mapsto maroonA maroonB maroonC maroonD maroonE mathbb",
  "mathbf mathbin mathcal mathchoice mathclap mathclose mathellipsis",
  "mathfrak mathinner mathit mathllap mathnormal mathop mathopen mathord",
  "mathpunct mathrel mathring mathrlap mathrm mathscr mathsf mathsfit",
  "mathsterling mathstrut mathtt max measuredangle medspace message mho mid",
  "middle min mintA mintB mintC minuscolon minuscoloncolon minuso mkern mod",
  "models mskip multimap nLeftarrow nLeftrightarrow nRightarrow nVDash",
  "nVdash nabla natnums natural ncong nearrow neg negmedspace negthickspace",
  "negthinspace neq newcommand newline nexists ngeq ngeqq ngeqslant ngtr",
  "nleftarrow nleftrightarrow nleq nleqq nleqslant nless nmid nobreak",
  "nobreakspace noexpand nolimits nonumber normalsize not notag notin notni",
  "nparallel nprec npreceq nrightarrow nshortmid nshortparallel nsim",
  "nsubseteq nsubseteqq nsucc nsucceq nsupseteq nsupseteqq ntriangleleft",
  "ntrianglelefteq ntriangleright ntrianglerighteq nvDash nvdash nwarrow",
  "odot oiiint oiint oint omega omicron ominus operatorname oplus orange",
  "ordinarycolon origof oslash otimes over overbrace overgroup",
  "overleftarrow overleftharpoon overleftrightarrow overline",
  "overlinesegment overrightarrow overrightharpoon overset owns parallel",
  "partial perp phantom phase phi pink pitchfork plim plusmn pmb pmod pod",
  "pounds prec precapprox preccurlyeq preceq precnapprox precneqq precnsim",
  "precsim prime prod projlim propto providecommand psi purple purpleA",
  "purpleB purpleC purpleD purpleE qquad quad rArr rBrace rVert raisebox",
  "rang rangle rarr ratio rbrace rbrack rceil real reals red redA redB redC",
  "redD redE relax relbar renewcommand restriction rfloor rgroup rhd rho",
  "right rightarrow rightarrowtail rightharpoondown rightharpoonup",
  "rightleftarrows rightleftharpoons rightrightarrows rightsquigarrow",
  "rightthreetimes risingdotseq rlap rmoustache rparen rrbracket rtimes",
  "rule rvert scriptscriptstyle scriptsize scriptstyle sdot searrow sec",
  "sect set setminus sharp shortmid shortparallel show sigma sim simcolon",
  "simcoloncolon simeq sin sinh sixptsize small smallfrown smallint",
  "smallsetminus smallsmile smash smile sout space spades spadesuit",
  "sphericalangle sqcap sqcup sqrt sqsubset sqsubseteq sqsupset sqsupseteq",
  "square stackrel star sub sube subset subseteq subseteqq subsetneq",
  "subsetneqq substack succ succapprox succcurlyeq succeq succnapprox",
  "succneqq succnsim succsim sum sup supe supset supseteq supseteqq",
  "supsetneq supsetneqq surd swarrow tag tan tanh tau tbinom tealA tealB",
  "tealC tealD tealE text textasciicircum textasciitilde textbackslash",
  "textbar textbardbl textbf textbraceleft textbraceright textcircled",
  "textcolor textcopyright textdagger textdaggerdbl textdegree textdollar",
  "textellipsis textemdash textendash textgreater textit textless textmd",
  "textnormal textquotedblleft textquotedblright textquoteleft",
  "textquoteright textregistered textrm textsf textsterling textstyle",
  "texttt textunderscore textup tfrac therefore theta thetasym thickapprox",
  "thicksim thickspace thinspace tilde times tiny tmspace top triangle",
  "triangledown triangleleft trianglelefteq triangleq triangleright",
  "trianglerighteq twoheadleftarrow twoheadrightarrow uArr uarr ulcorner",
  "underbar underbrace undergroup underleftarrow underleftrightarrow",
  "underline underlinesegment underrightarrow underset unlhd unrhd uparrow",
  "updownarrow upharpoonleft upharpoonright uplus upsilon upuparrows",
  "urcorner url utilde vDash varDelta varGamma varLambda varOmega varPhi",
  "varPi varPsi varSigma varTheta varUpsilon varXi varcoppa varepsilon",
  "varinjlim varkappa varliminf varlimsup varnothing varphi varpi",
  "varprojlim varpropto varrho varsigma varsubsetneq varsubsetneqq",
  "varsupsetneq varsupsetneqq vartheta vartriangle vartriangleleft",
  "vartriangleright varvdots vcentcolon vcenter vdash vdots vec vee veebar",
  "verb vert vphantom wedge weierp widecheck widehat widetilde xLeftarrow",
  "xLeftrightarrow xRightarrow xcancel xdef xhookleftarrow xhookrightarrow",
  "xleftarrow xleftequilibrium xleftharpoondown xleftharpoonup",
  "xleftrightarrow xleftrightharpoons xlongequal xmapsto xrightarrow",
  "xrightequilibrium xrightharpoondown xrightharpoonup xrightleftarrows",
  "xrightleftharpoons xtofrom xtwoheadleftarrow xtwoheadrightarrow yen zeta",].join(" ");

export const KATEX_COMMANDS: ReadonlySet<string> = new Set(
  KATEX_COMMAND_SOURCE.split(" "),
);

/**
 * Commands weak enough that finding one is not, on its own, evidence that the
 * surrounding text is maths. Colour and markup helpers appear in prose about
 * LaTeX far more often than in a formula a tutor actually wrote.
 */
const WEAK_TRIGGERS = new Set(
  (
    "red blue green orange pink purple gray teal gold maroon mint " +
    "redA redB redC redD redE blueA blueB blueC blueD blueE " +
    "greenA greenB greenC greenD greenE goldA goldB goldC goldD goldE " +
    "grayA grayB grayC grayD grayE grayF grayG grayH grayI " +
    "maroonA maroonB maroonC maroonD maroonE mintA mintB mintC " +
    "purpleA purpleB purpleC purpleD purpleE tealA tealB tealC tealD tealE " +
    "kaBlue kaGreen KaTeX LaTeX TeX url href verb relax show message " +
    "errmessage includegraphics htmlClass htmlData htmlId htmlStyle " +
    "text textrm textbf textit textnormal textup textmd textsf texttt"
  ).split(" "),
);

/**
 * Does this control sequence, found in running prose, argue that a formula
 * starts here? A trigger only opens the search — the whole candidate fragment
 * still has to be made of known commands (see `KATEX_COMMANDS`).
 */
export function isMathTriggerCommand(name: string): boolean {
  return (
    name.length >= 3 && KATEX_COMMANDS.has(name) && !WEAK_TRIGGERS.has(name)
  );
}

/** Is this a control sequence KaTeX would understand at all? */
export function isKnownLatexCommand(name: string): boolean {
  return name.length <= 2 || KATEX_COMMANDS.has(name);
}
