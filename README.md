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
```

Příkaz `vykres` dělá obrázky do produktových listů: rovnoběžný průmět bez
perspektivy, jen viditelné hrany, okótovaná šířka dole a výška vlevo.
Přepínače `--pohled zepredu|zezadu|zboku|shora|iso`, `--sirka` v pixelech
a `--pruhledne` pro pozadí bez bílé. Kosoúhlé `iso` se nekótuje — žádná hrana
obrázku tam neodpovídá rozměru tělesa.

Příkaz `sada` zpracuje celou řadu velikostí najednou a dá jim **společné
měřítko**: nejširší kus vyjde na `--sirka`, ostatní poměrně menší, takže se
obrázky dají postavit vedle sebe. Názvy souborů vznikají ze jmen STEPů.
Jednotlivou kresbu lze do takové řady doplnit přes `vykres --meritko` s
hodnotou v px/mm, kterou `sada` vypíše.

### Náčrtky skříní B3

```bash
$PY nacrtky.py "…/Vykresy PDF revize 3/STEP" "…/B3/nacrtky"
$PY montaz.py  "…/Skrin varianta 4 sloupce.stp" zada.png --meritko 0.9519
```

`nacrtky.py` vyrobí celou složku pro produktové listy naráz: nárys každé
velikosti, jeden bokorys (hloubka i výška jsou u všech stejné), iso nejmenší
skříně bez kót a záda s roztečemi na zeď. Všechno v jednom měřítku, takže to
jde postavit vedle sebe. Který kus dostane iso, bokorys a záda, říkají
přepínače `--iso`, `--bokorys` a `--zada` maskou na jméno souboru.

`montaz.py` je ta část se zády zvlášť. Hledá v zadním průmětu dvě řady
průchozích děr ⌀9, okótuje rozteče v horní liště a svislý odstup obou lišt.
Když záda nevypadají, jak mají, radši skončí chybou, než aby okótoval něco
jiného.

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
server.py         lokální server, procházení disku, nativní dialog
viewer/index.html prohlížeč (three.js, bez build kroku)
cache/            keš převodů, negitovaná
```
