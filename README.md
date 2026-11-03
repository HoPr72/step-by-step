# step-by-step

Prohlížeč a měřítko STEP souborů bez CADu. Načte sestavu, vytáhne názvy těles,
spočítá rozměry a objemy a umí v nich kótovat.

Jádro je **Open CASCADE (OCCT 8.0)** přes vazbu `OCP`. Žádné GUI, žádný
parametrický model, žádný recompute — jen načíst, odměřit, zobrazit.

## Instalace

```bash
python3 -m venv ~/.venvs/cad
~/.venvs/cad/bin/pip install build123d
```

Tím přijde i `cadquery-ocp` s celým OCCT (~730 MB). Nic se neinstaluje
systémově a `conda base` zůstane nedotčená.

Na render je navíc potřeba **Blender** v `/Applications`. `render.py` si ho
volá sám na pozadí; do venv se nic nepřidává, protože Blender si nese
vlastní Python.

## Prohlížeč

```bash
~/.venvs/cad/bin/python server.py ~/cesta/k/projektu
```

Otevře se v prohlížeči. Server projde zadané adresáře včetně podadresářů,
najde STEP soubory a převádí je na vyžádání — výsledek si keší v `cache/`
podle času změny zdroje, takže podruhé je to okamžité. Výchozí port je 8791
(`--port` ho přepíše); když je obsazený, zkusí dalších devět.

Tlačítko **SYSTÉMOVÝ DIALOG…** otevře nativní macOS dialog, takže se dá
sáhnout i mimo zadané kořeny.

### Ovládání

| | |
|---|---|
| levé tlačítko | výběr — klik nebo tažení rámečkem |
| prostřední | posun |
| pravé | rotace |
| kolečko | zoom |
| `Shift` | přidat do výběru |
| `Esc` | zrušit výběr a kóty |
| `M` | režim kótování |

Na trackpadu bez prostředního tlačítka: `Alt`+tažení otáčí, `Cmd`+tažení posouvá.

**Kótování:** zapni `KÓTA`, klikni dva body. Kurzor se přichytí na rohy a hrany
tělesa pod ním. Popisek kóty jde přetáhnout mimo kresbu — koncové body zůstanou
na místě a doplní se vynášecí čáry. Dvojklik kótu smaže.

## Příkazová řádka

```bash
PY=~/.venvs/cad/bin/python

$PY cli.py rozmery "dil.step"                  # tabulka těles do terminálu
$PY cli.py png     "dil.step" nahled.png       # technický render, 4 pohledy
$PY cli.py vykres  "dil.step" list.png         # perokresba s kótami
$PY cli.py sada    nacrtky/ "a.step" "b.step"  # perokresby v jednom měřítku
$PY cli.py json    vystup/ "a.step" "b.step"   # data pro statický prohlížeč

$PY render.py      "dil.step" render.png       # render přes Blender
```

Příkaz `vykres` dělá obrázky do produktových listů: rovnoběžný průmět bez
perspektivy, jen viditelné hrany, okótovaná šířka dole a výška vlevo.
Přepínače `--pohled zepredu|zezadu|zboku|zleva|shora|zdola|iso|iso-zdola`,
`--sirka` v pixelech a `--pruhledne` pro pozadí bez bílé. Kosoúhlé pohledy
se nekótují — žádná hrana obrázku tam neodpovídá rozměru tělesa.

Pohledy vycházejí z toho, **jak model leží**. Výchozí je CAD zvyk: osa Z
svisle, čelo proti ose Y. Když je model posazený jinak, řekne se to dvojicí
`--celo` a `--nahoru` a zbytek z toho plyne — bok je kolmý na obojí, záda
jsou proti čelu, iso je součet všech tří směrů:

```bash
$PY cli.py vykres "GK3_v5.step" celo.png --celo=-Z --nahoru=+X --meritko 3.0
```

Znaménko se píše s rovnítkem (`--celo=-Z`), jinak si `-Z` příkazová řádka
splete s přepínačem.

Příkaz `sada` zpracuje celou řadu velikostí najednou a dá jim **společné
měřítko**: nejširší kus vyjde na `--sirka`, ostatní poměrně menší, takže se
obrázky dají postavit vedle sebe. Názvy souborů vznikají ze jmen STEPů.
Jednotlivou kresbu lze do takové řady doplnit přes `vykres --meritko` s
hodnotou v px/mm, kterou `sada` vypíše.

### Náčrtky skříní B3

```bash
$PY nacrtky.py "…/Vykresy PDF revize 3/STEP" "…/B3/nacrtky" --meritko 1.0
$PY montaz.py  "…/Skrin varianta 4 sloupce.stp" zada.png --meritko 1.0

$PY brain.py   "…/Vykresy PDF revize 3/STEP" "…/B3/s-brainem/STEP"
$PY nacrtky.py "…/B3/s-brainem/STEP" "…/B3/s-brainem" --meritko 1.0 --iso vse --zada nic
```

`nacrtky.py` vyrobí celou složku pro produktové listy naráz: nárys každé
velikosti, jeden bokorys (hloubka i výška jsou u všech stejné), iso nejmenší
skříně bez kót a záda s roztečemi na zeď. Všechno v jednom měřítku, takže to
jde postavit vedle sebe. Který kus dostane iso, bokorys a záda, říkají
přepínače `--iso`, `--bokorys` a `--zada` maskou na jméno souboru; místo
masky se dá říct `vse` nebo `nic`. `--meritko 1.0` dává milimetr na pixel —
rozměr se pak dá z obrázku odečíst rovnou.

`montaz.py` je ta část se zády zvlášť. Hledá v zadním průmětu dvě řady
průchozích děr ⌀9, okótuje rozteče v horní liště a svislý odstup obou lišt.
Když záda nevypadají, jak mají, radši skončí chybou, než aby okótoval něco
jiného.

`brain.py` vymění nejpravější modul přihrádek za **brain** — sloupec
s elektronikou místo schránek. Zarovnává podle dvou navařovacích matic
nahoře, které jsou v obou modelech. Plech sloupce, který si brain nese po
svém, ze skříně vypadne, aby tam nestály dva přes sebe; je to ten u levého
kraje vyjímaného modulu. Záslepku do otvoru pro fabku umístí fabka, ta je
v obou modelech taky. Z brainu se přitom nepřenášejí drobné díly schované
uvnitř — osazená deska za displejem přišla s modelem displeje a v sestavě
skříně nemá co dělat; mez nastavuje `--drobne`, nula nechá brain celý.
Výstupem je STEP se zachovanou strukturou i názvy — kreslí se až potom,
`nacrtky.py` nad výstupním adresářem. Místo souboru snese i adresář
a projede celou řadu velikostí.

### Render

```bash
$PY render.py "GK3_v5.step" render.png --celo=-Z --nahoru=+X \
    --obrazek idle-screen.png --azimut 30 --elevace 23.5
```

`render.py` pošle model do **Blenderu** a vrátí obrázek s materiály, měkkým
světlem a stínem na zeď. Blender běží na pozadí, nic se neotevírá na
obrazovce. Model se otočí podle stejné dvojice `--celo` a `--nahoru` jako
perokresby, postaví se zády ke zdi a dostane materiály podle názvů těles:
`body` černý matný lak, `display` černé sklo, co zbyde je nerez. Obrazovka
se hledá geometricky — je to největší rovná plocha koukající dopředu — a
lepí se na ni `--obrazek`.

Kamera se zadává úhly, ne souřadnicemi: `--azimut` je odklon od čelního
pohledu doprava, `--elevace` výška nad vodorovnou, `--objektiv` ohnisko
v milimetrech na kinofilm. Odstup si dopočítá sama tak, aby model padl do
záběru, `--zaber` k tomu přidá rezervu. Kosoúhlý pohled jako v perokresbách
je 45° a 35°.

Vzhled ladí `--cerna` (odrazivost laku), `--drsnost`, `--expozice`, `--svit`
displeje a výkony tří světel `--klic`, `--vypln`, `--strop`.

Práce je rozdělená na dva kusy, protože Blender nemá OCCT a venv nemá bpy:
`render.py` připraví sítě a popis scény, `blender_scena.py` z toho uvnitř
Blenderu postaví scénu a vyrenderuje ji.

Příkaz `json` vyrobí složku, kterou prohlížeč umí servírovat i bez serveru —
stačí ji dát vedle `viewer/index.html` jako `viewer/models/`. V tom režimu
odpadá procházení disku a nabízí se jen zabalené modely.

## Co stojí za vědění

**Názvy těles** nejsou tam, kde by je člověk čekal. `build123d.import_step()`
je nevrací vůbec; sedí v XCAF struktuře dokumentu a čtou se přes
`STEPCAFControl_Reader`. Dokument je přitom nutné držet v proměnné — jakmile
ho Python uklidí, `ShapeTool` ukazuje do prázdna a vrátí nula těles.

**Diakritika** je ve STEPu escapovaná podle ISO 10303-21: `\X\E1` je jeden znak
kódu 0xE1, `\X2\....\X0\` je UTF-16. OCCT 8.0 to v této verzi nerozkóduje ani
s nastaveným `read.step.codepage` a nechá v názvu U+FFFD, takže si to `stepkit`
dekóduje sám a napáruje na poškozené názvy přes masku. Předpokládá CP1250
(SolidWorks CZ) — pro jiný jazyk stačí změnit `STEP_CODEPAGE`.

Některé exporty ze SolidWorks mají náhradní znaky zapsané **rovnou ve zdroji**
(`\X2\FFFDFFFD\X0\`). Tam už se nedá zachránit nic a nahrazuje se otazníkem.

**Osa Z je svislá**, jak je v CADu zvykem. three.js počítá s Y nahoru, takže
prohlížeč přepíná `camera.up` — bez toho ukazuje pohled zboku shora.

**Kóta má jediný stupeň volnosti navíc.** Leží v rovině, která prochází měřenou
úsečkou: kótovací čára je s ní rovnoběžná a vynášecí čáry na ni kolmé, jak to
předepisuje norma. Volné zůstává natočení té roviny kolem úsečky, a to se
přichytává po 45° k hlavní ose nejméně rovnoběžné s měřenou úsečkou — u
vodorovné kóty tedy sedne do roviny Front nebo Top, nebo na půlku mezi nimi.
Tažení myší nastavuje jen odstup; podélná složka se zahazuje.

**Perokresba je rovnoběžný průmět**, ne render. Hrany projdou přes HLR
(odstranění neviditelných hran) a kreslí se jako čáry, takže okraj obrázku
odpovídá skutečnému rozměru a jde rovnou okótovat — u perspektivy by to
neplatilo. PIL čáry nevyhlazuje, proto se kreslí do čtyřnásobného plátna
a na konci se zmenšuje.

**Stejná šířka v pixelech není stejné měřítko.** Když se každá velikost
roztáhne na 1600 px, vyjde na obrázku nejmenší skříň stejně velká jako
největší — na srovnávací tabulce pak vypadá dvousloupcová větší než
osmisloupcová. Proto `sada` počítá měřítko ze všech kusů najednou: průmět je
to pomalé, kreslení skoro nic, takže se všechno promítne napřed a kreslí se
až s měřítkem na ruce. Tloušťka čar a velikost písma se drží nominální
šířky, ne skutečné, aby byly napříč řadou stejné.

Náčrtky B3 se kreslí v `--meritko 1.0`, tedy **milimetr na pixel**. Měřítko
dopočítané na danou šířku vyjde na číslo jako 0,9519, které nikomu nic
neříká; s jedničkou se rozměr z obrázku odečte rovnou a kóty jdou ověřit
pravítkem v prohlížeči.

**Kružnice přežijí průmět.** Díra v rovné stěně se promítne zase jako
kružnice, a OCCT ji takovou i vrátí — i s poloměrem a středem v rovině
průmětu. Díry se proto nehledají v modelu a nic se nepřepočítává zpátky:
střed vyjde přesně tam, kam se kótuje. Z kružnic se berou jen celé, protože
oblouček na hraně zaoblení není díra, a stejné středy se slučují — průmět
vrátí soustřednou kružnici za každou plochu, kterou díra protne.

**Rozvržení plátna se vede podle toho, co na něm bude.** Kóta může ležet
i mimo těleso, takže se nejdřív spočítá obrys všeho včetně popisků a teprve
pak se zakládá obrázek. Proto se kóty kreslí dvakrát: napoprvé nanečisto,
jen aby se změřily.

**Sestavu jde upravit, aniž by se rozsypala.** STEP se čte do XCAF dokumentu
a ten je editovatelný strom: `RemoveComponent` vyndá modul, `AddComponent`
přidá díl odjinud. Tvary na dokumentu nezávisí, takže se berou rovnou
z druhého souboru a jen se jim přepočítá poloha. Zapisuje se přes
`STEPCAFControl_Writer`, který si nese názvy i strukturu — `STEPControl_Writer`
by vrátil jen hromadu těles bez jmen.

**Zarovnává se podle dílů, ne podle souřadnic.** Dvojice matic určuje polohu
i natočení. `brain.py` si napřed ověří, že obě dvojice mají stejné rozestupy,
a teprve pak počítá rozdíl středů — kdyby se díly lišily, skončí chybou,
místo aby je napasoval násilím.

**Značka, která se opakuje, není značka.** Matice vypadají ve všech sloupcích
stejně, takže hledat podle nich ten správný plech znamená trefit se do toho,
na který se narazí dřív. U třísloupce to vyšlo, u dvousloupce by brain
přistál o celou rozteč vedle skříně. Plech se proto vybírá podle polohy vůči
vyjímanému modulu a nakonec se ověří, že brain opravdu padl do místa po něm.
Posuny pak vyjdou na násobky rozteče 180 mm, a to je samo o sobě kontrola.

Vyšlo při tom najevo, že brain je namodelovaný přesně v soustavě třísloupcové
skříně: tam zbývá posun 0,4 mm ve svislici, a to jen proto, že brain veze
o 0,4 mm kratší revizi plechu sloupce.

**Černá není nula.** Černý matný lak zadaný jako čistá čerň se na obrázku
chová jako díra: nemá co odrážet, takže z něj nezbude tvar, jen silueta.
Skutečný lak odráží kolem procenta až pěti procent světla a právě ta troška
dělá přechody po hranách. Výchozí `--cerna 0.007` vyjde na obrázku kolem
`#393a3b` — v okolí světlé zdi to čte jako černá, a přitom je vidět zkosení
i zaoblené rohy.

**Světla na malý předmět jsou slabá.** Blender počítá ve wattech a vzdálenost
se podepíše na druhou. Napoprvé jsem dal klíčové světlo 260 W jako do pokoje,
jenže to svítí na předmět velký 22 cm ze vzdálenosti půl metru — všechno
vyšlo bílé. Správně je to kolem 14 W. A černou nespraví silnější světlo,
jen posune celý obrázek nahoru; na to je expozice.

**Zobrazovací křivka není kosmetika.** `Standard` ustřelí zeď do bílé a
z displeje udělá placku. `AgX` stejnou scénu srovná: zeď drží střední šedou
jako v referenci a na displeji zůstane text čitelný. Renderuje se v obojím
stejně dlouho, rozdíl je jen v tom, jak se čísla převedou na pixely.

**Jak model leží, z modelu nevyčteš.** Soustava souřadnic nese jen to, co do
ní kdo dal; že je GK3 na výšku, že členitá hrana je dole a konektory míří
k zemi, v souboru nikde nestojí. Geometrie svádí ke špatnému odhadu: displej
je sám o sobě na šířku a nápisy na zádech jsou psané podél hrany. Proto
orientace není v kódu natvrdo, ale zadává se dvojicí os — a pozná se podle
toho, že se nápisy na zádech čtou vodorovně.

**Co není vidět, nemusí tam být.** Model displeje s sebou vezl celý svůj
vnitřek — osazenou desku a na ní 156 SMD součástek, distanční sloupky,
konektory, flex kabely. Ve skříni z toho není vidět nic a neslo to skoro
tři čtvrtiny velikosti souboru: 28 → 8 MB na kus, u celé řady 186 → 54 MB.
Vyhazuje se geometricky, ne podle jmen: díl musí být menší než zadaná mez
**a zároveň** celý uvnitř největšího tělesa. Co z krabice čouhá ven, zůstává,
takže matice pro zarovnání nemůže žádná mez odnést. A že se nic neztratilo,
ukážou kresby — po přegenerování vyšly bit po bitu stejné.

**Výběr rámečkem** je typu *crossing* přes obalové kvádry: chytí i těleso,
jehož kvádr do rámečku zasahuje, ale geometrie ne. U šikmých a tenkých dílů
to vybere víc, než člověk čeká.

**Skrytá tělesa** zmizí ze scény a přestanou se dát vybrat i trefit kótou,
ale do objemu a hmotnosti celé sestavy se počítají dál.

## Struktura

```
stepkit.py        čtení STEP, názvy, mesh, rozměry, objemy
vykres.py         průmět, měřítko, kóty, kresba do PNG
cli.py            příkazová řádka (rozmery / png / vykres / sada / json)
nacrtky.py        celá složka náčrtků pro produktové listy B3
montaz.py         záda s roztečemi na zeď
brain.py          výměna krajního modulu za brain
render.py         render přes Blender — materiály, světlo, stín
blender_scena.py  druhá půlka renderu, běží uvnitř Blenderu
server.py         lokální server, procházení disku, nativní dialog
viewer/index.html prohlížeč (three.js, bez build kroku)
cache/            keš převodů, negitovaná
```
