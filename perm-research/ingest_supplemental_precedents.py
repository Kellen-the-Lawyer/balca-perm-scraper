#!/usr/bin/env python3
"""
Supplemental ingest: complete vol 11, vol 10, vol 9 (and vol 8 once confirmed).
Upserts into existing precedent_decisions table.
"""
import asyncio, logging, os, re, io
import httpx, pdfplumber, asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

SAVE_DIR = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/AAO Precedents"
DB_URL   = "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
B        = "https://www.justice.gov"
HEADERS  = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

os.makedirs(SAVE_DIR, exist_ok=True)

# Complete vol 11 + vol 10 + vol 9 + vol 8 (placeholder until confirmed)
SUPPLEMENTAL = [
    # ── Vol 11 (complete — 114 entries) ──────────────────────────────────────
    (11,"11 I&N Dec. 1","Petuolglu",1964,"D.D.",B+"/eoir/vll/intdec/vol11/1418.pdf"),
    (11,"11 I&N Dec. 3","Toth",1964,"R.C.",B+"/eoir/vll/intdec/vol11/1419.pdf"),
    (11,"11 I&N Dec. 9","Landolfi",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1421.pdf"),
    (11,"11 I&N Dec. 21","Vaccarello",1964,"OIC",B+"/eoir/vll/intdec/vol11/1424.pdf"),
    (11,"11 I&N Dec. 25","Young",1964,"D.D.",B+"/eoir/vll/intdec/vol11/1425.pdf"),
    (11,"11 I&N Dec. 32","Madalla",1964,"D.D.",B+"/eoir/vll/intdec/vol11/1427.pdf"),
    (11,"11 I&N Dec. 51","Farley",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1432.pdf"),
    (11,"11 I&N Dec. 63","Kraus Periodicals Inc.",1964,"R.C.",B+"/eoir/vll/intdec/vol11/1434.pdf"),
    (11,"11 I&N Dec. 65","Rexer",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1435.pdf"),
    (11,"11 I&N Dec. 67","Ormos",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1436.pdf"),
    (11,"11 I&N Dec. 69","Kim",1964,"R.C.",B+"/eoir/vll/intdec/vol11/1437.pdf"),
    (11,"11 I&N Dec. 71","Colletti",1965,"Asst. Comm'r",B+"/eoir/vll/intdec/vol11/1438.pdf"),
    (11,"11 I&N Dec. 76","Psalidas",1965,"BIA",B+"/eoir/vll/intdec/vol11/1440.pdf"),
    (11,"11 I&N Dec. 96","Lee",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1441.pdf"),
    (11,"11 I&N Dec. 99","A-",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1442.pdf"),
    (11,"11 I&N Dec. 121","De Los Santos",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1447.pdf"),
    (11,"11 I&N Dec. 123","Di Pietra",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1448.pdf"),
    (11,"11 I&N Dec. 125","Alvan",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1449.pdf"),
    (11,"11 I&N Dec. 128","Cintioli",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1450.pdf"),
    (11,"11 I&N Dec. 130","Bresnahan",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1451.pdf"),
    (11,"11 I&N Dec. 131","Chin",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1452.pdf"),
    (11,"11 I&N Dec. 136","B-",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1454.pdf"),
    (11,"11 I&N Dec. 138","Chang",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1455.pdf"),
    (11,"11 I&N Dec. 140","Brunner",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1456.pdf"),
    (11,"11 I&N Dec. 142","Hersh",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1457.pdf"),
    (11,"11 I&N Dec. 144","Erginsoy",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1458.pdf"),
    (11,"11 I&N Dec. 146","Santillano",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1459.pdf"),
    (11,"11 I&N Dec. 148","Lew",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1460.pdf"),
    (11,"11 I&N Dec. 154","College of the Scriptures",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1462.pdf"),
    (11,"11 I&N Dec. 157","Masauyama",1965,"Acting R.C.",B+"/eoir/vll/intdec/vol11/1463.pdf"),
    (11,"11 I&N Dec. 159","Uy",1965,"BIA",B+"/eoir/vll/intdec/vol11/1464.pdf"),
    (11,"11 I&N Dec. 167","Rubio-Vargas",1965,"BIA",B+"/eoir/vll/intdec/vol11/1466.pdf"),
    (11,"11 I&N Dec. 190","Huang",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1472.pdf"),
    (11,"11 I&N Dec. 193","Hroncich",1965,"BIA",B+"/eoir/vll/intdec/vol11/1473.pdf"),
    (11,"11 I&N Dec. 224","Lavoie",1965,"BIA",B+"/eoir/vll/intdec/vol11/1481.pdf"),
    (11,"11 I&N Dec. 253","Wong",1965,"Acting R.C.",B+"/eoir/vll/intdec/vol11/1488.pdf"),
    (11,"11 I&N Dec. 255","Willner",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1489.pdf"),
    (11,"11 I&N Dec. 261","Manion",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1491.pdf"),
    (11,"11 I&N Dec. 277","Shaw",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1496.pdf"),
    (11,"11 I&N Dec. 282","Wang",1965,"Acting R.C.",B+"/eoir/vll/intdec/vol11/1497.pdf"),
    (11,"11 I&N Dec. 285","Sparmann",1965,"Acting D.D.",B+"/eoir/vll/intdec/vol11/1498.pdf"),
    (11,"11 I&N Dec. 290","Seto",1965,"Acting R.C.",B+"/eoir/vll/intdec/vol11/1500.pdf"),
    (11,"11 I&N Dec. 293","Toba",1965,"Acting R.C.",B+"/eoir/vll/intdec/vol11/1501.pdf"),
    (11,"11 I&N Dec. 300","Davoudlarian",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1503.pdf"),
    (11,"11 I&N Dec. 302","Russell, et al.",1965,"Deputy A.C.",B+"/eoir/vll/intdec/vol11/1504.pdf"),
    (11,"11 I&N Dec. 306","Mansour",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1505.pdf"),
    (11,"11 I&N Dec. 333","Jimenez",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1512.pdf"),
    (11,"11 I&N Dec. 351","Bufalino",1965,"BIA",B+"/eoir/vll/intdec/vol11/1517.pdf"),
    (11,"11 I&N Dec. 363","Sasano",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1518.pdf"),
    (11,"11 I&N Dec. 391","Kaufmann",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1524.pdf"),
    (11,"11 I&N Dec. 393","Iguanti",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1525.pdf"),
    (11,"11 I&N Dec. 395","Tran",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1526.pdf"),
    (11,"11 I&N Dec. 397","Brandon's Professional Schools",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1527.pdf"),
    (11,"11 I&N Dec. 409","Olivera",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1529.pdf"),
    (11,"11 I&N Dec. 411","Penninsula School, Ltd.",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1530.pdf"),
    (11,"11 I&N Dec. 424","Koyama",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1534.pdf"),
    (11,"11 I&N Dec. 427","Pacheco",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1535.pdf"),
    (11,"11 I&N Dec. 430","Minei",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1536.pdf"),
    (11,"11 I&N Dec. 462","Peak Productions, Inc.",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1544.pdf"),
    (11,"11 I&N Dec. 464","Habib",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1545.pdf"),
    (11,"11 I&N Dec. 473","Lovell",1965,"R.C.",B+"/eoir/vll/intdec/vol11/1547.pdf"),
    (11,"11 I&N Dec. 493","Brantigan",1965,"BIA",B+"/eoir/vll/intdec/vol11/1553.pdf"),
    (11,"11 I&N Dec. 496","Arabian",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1554.pdf"),
    (11,"11 I&N Dec. 506","Bridges",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1557.pdf"),
    (11,"11 I&N Dec. 509","Kim",1965,"D.D.",B+"/eoir/vll/intdec/vol11/1558.pdf"),
    (11,"11 I&N Dec. 512","Bass",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1559.pdf"),
    (11,"11 I&N Dec. 518","Drachman",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1561.pdf"),
    (11,"11 I&N Dec. 534","Lambeth Productions",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1566.pdf"),
    (11,"11 I&N Dec. 558","Cruikshank",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1573.pdf"),
    (11,"11 I&N Dec. 560","B-",1966,"A.C.",B+"/eoir/vll/intdec/vol11/1574.pdf"),
    (11,"11 I&N Dec. 565","De Lucia",1966,"BIA",B+"/eoir/vll/intdec/vol11/1575.pdf"),
    (11,"11 I&N Dec. 583","Duchneskie",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1576.pdf"),
    (11,"11 I&N Dec. 585","Agryros",1966,"BIA",B+"/eoir/vll/intdec/vol11/1577.pdf"),
    (11,"11 I&N Dec. 599","Nimmons",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1580.pdf"),
    (11,"11 I&N Dec. 601","Lee",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1581.pdf"),
    (11,"11 I&N Dec. 635","Peczkowski",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1592.pdf"),
    (11,"11 I&N Dec. 643","Stamataides",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1594.pdf"),
    (11,"11 I&N Dec. 647","Courpas",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1595.pdf"),
    (11,"11 I&N Dec. 652","Hseuh",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1597.pdf"),
    (11,"11 I&N Dec. 654","Balbada",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1598.pdf"),
    (11,"11 I&N Dec. 657","Frank",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1599.pdf"),
    (11,"11 I&N Dec. 660","Asuncion",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1600.pdf"),
    (11,"11 I&N Dec. 672","Strippa",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1602.pdf"),
    (11,"11 I&N Dec. 678","Watson",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1604.pdf"),
    (11,"11 I&N Dec. 686","Shin",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1606.pdf"),
    (11,"11 I&N Dec. 694","Yen",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1609.pdf"),
    (11,"11 I&N Dec. 697","Wu",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1610.pdf"),
    (11,"11 I&N Dec. 710","Lee",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1615.pdf"),
    (11,"11 I&N Dec. 715","Raychaudhuri",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1617.pdf"),
    (11,"11 I&N Dec. 717","Monteran",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1618.pdf"),
    (11,"11 I&N Dec. 751","Samerjian",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1627.pdf"),
    (11,"11 I&N Dec. 764","Glencoe Press",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1630.pdf"),
    (11,"11 I&N Dec. 777","Basu",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1633.pdf"),
    (11,"11 I&N Dec. 779","Vos",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1634.pdf"),
    (11,"11 I&N Dec. 785","Kozielczk",1966,"Deputy A.C.",B+"/eoir/vll/intdec/vol11/1636.pdf"),
    (11,"11 I&N Dec. 800","Devnani",1966,"Acting D.D.",B+"/eoir/vll/intdec/vol11/1640.pdf"),
    (11,"11 I&N Dec. 802","Bedi",1966,"Acting D.D.",B+"/eoir/vll/intdec/vol11/1641.pdf"),
    (11,"11 I&N Dec. 805","Locicero",1966,"BIA",B+"/eoir/vll/intdec/vol11/1642.pdf"),
    (11,"11 I&N Dec. 815","Konishi",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1644.pdf"),
    (11,"11 I&N Dec. 817","Dessi",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1645.pdf"),
    (11,"11 I&N Dec. 824","Hira",1966,"BIA",B+"/eoir/vll/intdec/vol11/1647.pdf"),
    (11,"11 I&N Dec. 843","Nakatsugawa",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1651.pdf"),
    (11,"11 I&N Dec. 845","Shao",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1652.pdf"),
    (11,"11 I&N Dec. 847","Shih",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1653.pdf"),
    (11,"11 I&N Dec. 860","Delis",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1657.pdf"),
    (11,"11 I&N Dec. 867","Wojciechowski",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1659.pdf"),
    (11,"11 I&N Dec. 869","Roldan",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1660.pdf"),
    (11,"11 I&N Dec. 876","Ku",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1662.pdf"),
    (11,"11 I&N Dec. 878","Lettman",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1663.pdf"),
    (11,"11 I&N Dec. 881","Chu",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1664.pdf"),
    (11,"11 I&N Dec. 896","War Memorial Hospital",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1668.pdf"),
    (11,"11 I&N Dec. 898","McGowan",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1669.pdf"),
    (11,"11 I&N Dec. 901","Rodriguez",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1670.pdf"),
    (11,"11 I&N Dec. 904","Nafahu",1966,"R.C.",B+"/eoir/vll/intdec/vol11/1671.pdf"),
    (11,"11 I&N Dec. 909","Duncan",1966,"D.D.",B+"/eoir/vll/intdec/vol11/1672.pdf"),
    # ── Vol 10 ────────────────────────────────────────────────────────────────
    (10,"10 I&N Dec. 103","Szajlai",1962,"A.C.",B+"/eoir/vll/intdec/vol10/1252.pdf"),
    (10,"10 I&N Dec. 139","Picone",1962,"BIA",B+"/eoir/vll/intdec/vol10/1259.pdf"),
    (10,"10 I&N Dec. 317","St. Demetrios Greek Orthodox Church",1963,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol10/1293.pdf"),
    (10,"10 I&N Dec. 355","Amico",1963,"D.D.",B+"/eoir/vll/intdec/vol10/1299.pdf"),
    (10,"10 I&N Dec. 394","Monsatra",1963,"D.D.",B+"/eoir/vll/intdec/vol10/1309.pdf"),
    (10,"10 I&N Dec. 425","Kobayashi and Doi",1964,"D.D.",B+"/eoir/vll/intdec/vol10/1313.pdf"),
    (10,"10 I&N Dec. 484","Cunney",1964,"D.D.",B+"/eoir/vll/intdec/vol10/1327.pdf"),
    (10,"10 I&N Dec. 593","Adamo",1964,"BIA",B+"/eoir/vll/intdec/vol10/1349.pdf"),
    (10,"10 I&N Dec. 620","Escarnado",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1356.pdf"),
    (10,"10 I&N Dec. 622","Boireau",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1357.pdf"),
    (10,"10 I&N Dec. 624","Suh",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1358.pdf"),
    (10,"10 I&N Dec. 626","Ko",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1359.pdf"),
    (10,"10 I&N Dec. 628","Zavala",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1360.pdf"),
    (10,"10 I&N Dec. 630","Sanchez-Monreal",1964,"BIA",B+"/eoir/vll/intdec/vol10/1361.pdf"),
    (10,"10 I&N Dec. 640","Michigan State University",1963,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1362.pdf"),
    (10,"10 I&N Dec. 642","Michigan State University",1963,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1363.pdf"),
    (10,"10 I&N Dec. 644","Miyazaki Travel Agency Inc.",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1364.pdf"),
    (10,"10 I&N Dec. 646","Kyriakarkos",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1365.pdf"),
    (10,"10 I&N Dec. 647","Saunders",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1366.pdf"),
    (10,"10 I&N Dec. 649","Papro",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1367.pdf"),
    (10,"10 I&N Dec. 651","Wolfe",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1368.pdf"),
    (10,"10 I&N Dec. 653","Lim",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1369.pdf"),
    (10,"10 I&N Dec. 654","Contopoulos",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1370.pdf"),
    (10,"10 I&N Dec. 659","Franklin Pierce College",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1371.pdf"),
    (10,"10 I&N Dec. 661","Esposito",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1372.pdf"),
    (10,"10 I&N Dec. 663","Peterson",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1373.pdf"),
    (10,"10 I&N Dec. 666","Lewis",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1374.pdf"),
    (10,"10 I&N Dec. 668","Guia",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1375.pdf"),
    (10,"10 I&N Dec. 669","Schonfeld",1964,"Act. R.C.",B+"/eoir/vll/intdec/vol10/1376.pdf"),
    (10,"10 I&N Dec. 675","Acosta",1964,"BIA",B+"/eoir/vll/intdec/vol10/1378.pdf"),
    (10,"10 I&N Dec. 688","Sweed",1964,"BIA",B+"/eoir/vll/intdec/vol10/1382.pdf"),
    (10,"10 I&N Dec. 691","T-E-C-",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1383.pdf"),
    (10,"10 I&N Dec. 694","J-F-D-",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1384.pdf"),
    (10,"10 I&N Dec. 696","R-R-",1963,"OIC",B+"/eoir/vll/intdec/vol10/1385.pdf"),
    (10,"10 I&N Dec. 699","Yaron et al.",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1386.pdf"),
    (10,"10 I&N Dec. 701","Lee",1963,"Dep. A.C.",B+"/eoir/vll/intdec/vol10/1387.pdf"),
    (10,"10 I&N Dec. 706","Buckland",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1388.pdf"),
    (10,"10 I&N Dec. 708","Moorman",1964,"D.D.",B+"/eoir/vll/intdec/vol10/1389.pdf"),
    (10,"10 I&N Dec. 710","Grecian Palace",1962,"R.C.",B+"/eoir/vll/intdec/vol10/1390.pdf"),
    (10,"10 I&N Dec. 712","Bisulca",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1391.pdf"),
    (10,"10 I&N Dec. 715","University of California Medical Center",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1392.pdf"),
    (10,"10 I&N Dec. 717","Tamura",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1393.pdf"),
    (10,"10 I&N Dec. 740","Prieto-Perez",1964,"BIA",B+"/eoir/vll/intdec/vol10/1399.pdf"),
    (10,"10 I&N Dec. 750","Gupta",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1402.pdf"),
    (10,"10 I&N Dec. 753","Poindexter Gallery",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1403.pdf"),
    (10,"10 I&N Dec. 755","Barnes",1964,"Act. OIC & R.C.",B+"/eoir/vll/intdec/vol10/1404.pdf"),
    (10,"10 I&N Dec. 758","Sinha",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1405.pdf"),
    (10,"10 I&N Dec. 761","Del Conte",1964,"D.D.",B+"/eoir/vll/intdec/vol10/1406.pdf"),
    (10,"10 I&N Dec. 764","Alberga",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1407.pdf"),
    (10,"10 I&N Dec. 767","Duran-Montoya",1963,"R.C.",B+"/eoir/vll/intdec/vol10/1408.pdf"),
    (10,"10 I&N Dec. 770","Rocha",1964,"BIA",B+"/eoir/vll/intdec/vol10/1409.pdf"),
    (10,"10 I&N Dec. 774","Azmitia",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1410.pdf"),
    (10,"10 I&N Dec. 776","Martinez-Torres",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1411.pdf"),
    (10,"10 I&N Dec. 785","Hadad",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1414.pdf"),
    (10,"10 I&N Dec. 787","Ikemiya",1964,"D.D.",B+"/eoir/vll/intdec/vol10/1415.pdf"),
    (10,"10 I&N Dec. 794","Dun-Rite Kitchen Cabinet Corp.",1964,"R.C.",B+"/eoir/vll/intdec/vol10/1417.pdf"),
    # ── Vol 9 ─────────────────────────────────────────────────────────────────
    (9,"9 I&N Dec. 30","P-R-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1092.pdf"),
    (9,"9 I&N Dec. 38","G-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1093.pdf"),
    (9,"9 I&N Dec. 41","C-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1094.pdf"),
    (9,"9 I&N Dec. 50","K-B-N-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1096.pdf"),
    (9,"9 I&N Dec. 54","F-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1097.pdf"),
    (9,"9 I&N Dec. 64","G-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1100.pdf"),
    (9,"9 I&N Dec. 67","A-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1101.pdf"),
    (9,"9 I&N Dec. 98","B-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1108.pdf"),
    (9,"9 I&N Dec. 100","C-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1109.pdf"),
    (9,"9 I&N Dec. 103","R-E-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1110.pdf"),
    (9,"9 I&N Dec. 106","H-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1111.pdf"),
    (9,"9 I&N Dec. 127","T-",1960,"BIA",B+"/eoir/vll/intdec/vol09/1115.pdf"),
    (9,"9 I&N Dec. 141","C-N-J-",1960,"A.C.",B+"/eoir/vll/intdec/vol09/1117.pdf"),
    (9,"9 I&N Dec. 161","Y-K-W-",1961,"A.G.",B+"/eoir/vll/intdec/vol09/1122.pdf"),
    (9,"9 I&N Dec. 188","O-M-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1124.pdf"),
    (9,"9 I&N Dec. 249","A-",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1134.pdf"),
    (9,"9 I&N Dec. 265","C-H-",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1136.pdf"),
    (9,"9 I&N Dec. 299","S-",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1144.pdf"),
    (9,"9 I&N Dec. 329","Z-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1149.pdf"),
    (9,"9 I&N Dec. 336","K-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1151.pdf"),
    (9,"9 I&N Dec. 362","P-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1155.pdf"),
    (9,"9 I&N Dec. 411","H-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1163.pdf"),
    (9,"9 I&N Dec. 433","C-",1961,"BIA",B+"/eoir/vll/intdec/vol09/1167.pdf"),
    (9,"9 I&N Dec. 436","S- and B-C-",1961,"A.G.",B+"/eoir/vll/intdec/vol09/1168.pdf"),
    (9,"9 I&N Dec. 467","D-S-, Inc.",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1171.pdf"),
    (9,"9 I&N Dec. 478","T-",1961,"Comm'r",B+"/eoir/vll/intdec/vol09/1173.pdf"),
    (9,"9 I&N Dec. 479","E-",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1174.pdf"),
    (9,"9 I&N Dec. 482","C-A-",1961,"A.C.",B+"/eoir/vll/intdec/vol09/1175.pdf"),
]


async def download_and_extract(client, entry):
    vol, citation, party, year, body, url = entry
    safe  = re.sub(r"[^\w\-]", "_", citation)
    fpath = os.path.join(SAVE_DIR, safe + ".pdf")

    if not os.path.exists(fpath):
        try:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(resp.content)
            await asyncio.sleep(0.3)
        except Exception as e:
            log.warning(f"  Download FAILED {citation}: {e}")
            return dict(volume=vol,citation=citation,party_name=party,year=year,
                        body=body,pdf_url=url,pdf_path=None,full_text="")
    else:
        log.info(f"  Cached: {citation}")

    try:
        with pdfplumber.open(fpath) as pdf:
            text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        log.warning(f"  Extract FAILED {citation}: {e}")
        text = ""

    return dict(volume=vol,citation=citation,party_name=party,year=year,
                body=body,pdf_url=url,pdf_path=fpath,full_text=text)


async def main():
    conn = await asyncpg.connect(DB_URL)
    log.info(f"Processing {len(SUPPLEMENTAL)} supplemental entries.")

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        for i, entry in enumerate(SUPPLEMENTAL):
            citation = entry[1]
            log.info(f"[{i+1}/{len(SUPPLEMENTAL)}] {citation} — {entry[2]}")
            d = await download_and_extract(client, entry)

            await conn.execute("""
                INSERT INTO precedent_decisions
                  (volume,citation,party_name,year,body,pdf_url,pdf_path,full_text)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (citation) DO UPDATE SET
                  full_text  = EXCLUDED.full_text,
                  pdf_path   = EXCLUDED.pdf_path,
                  party_name = EXCLUDED.party_name,
                  volume     = EXCLUDED.volume
            """, d["volume"],d["citation"],d["party_name"],d["year"],
                 d["body"],d["pdf_url"],d["pdf_path"],d["full_text"])

    total = await conn.fetchval("SELECT COUNT(*) FROM precedent_decisions")
    by_vol = await conn.fetch(
        "SELECT volume, COUNT(*) as n FROM precedent_decisions GROUP BY volume ORDER BY volume DESC")
    log.info(f"\nTotal in DB: {total}")
    for row in by_vol:
        log.info(f"  Vol {row['volume']}: {row['n']}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
