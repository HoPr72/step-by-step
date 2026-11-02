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
$PY cli.py json    vystup/ "a.step" "b.step"   # data pro statický prohlížeč
```

Příkaz `vykres` dělá obrázky do produktových listů: rovnoběžný průmět bez
perspektivy, jen viditelné hrany, okótovaná šířka dole a výška vlevo.
Přepínače `--pohled zepredu|zezadu|zboku|shora`, `--sirka` v pixelech
a `--pruhledne` pro pozadí bez bílé.

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

**Výběr rámečkem** je typu *crossing* přes obalové kvádry: chytí i těleso,
jehož kvádr do rámečku zasahuje, ale geometrie ne. U šikmých a tenkých dílů
to vybere víc, než člověk čeká.

**Skrytá tělesa** zmizí ze scény a přestanou se dát vybrat i trefit kótou,
ale do objemu a hmotnosti celé sestavy se počítají dál.

## Struktura

```
stepkit.py        čtení STEP, názvy, mesh, rozměry, objemy
cli.py            příkazová řádka (rozmery / png / json)
server.py         lokální server, procházení disku, nativní dialog
viewer/index.html prohlížeč (three.js, bez build kroku)
cache/            keš převodů, negitovaná
```
