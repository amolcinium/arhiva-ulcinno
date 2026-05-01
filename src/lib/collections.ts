/**
 * Curated thematic collections — editorial starter packs across our archive.
 * Each collection defines a Supabase query that returns its members.
 */

export interface Collection {
  slug: string;
  title: string;
  emoji: string;
  description: string;
  /** Filter spec — applied as Supabase query params */
  filter: {
    sources?: string[];
    locations?: string[];
    yearMin?: number;
    yearMax?: number;
    qLike?: string[]; // ILIKE patterns matched against title/snippet
  };
  highlight?: string; // Optional intro text for the page
}

export const COLLECTIONS: Collection[] = [
  {
    slug: 'mletacki-ulcinj',
    title: 'Mletački Ulcinj 1405–1571',
    emoji: '⚓',
    description: 'Period mletačke vlasti — Senato Mar izvještaji, kapetani, mletačke karte (Camocio, Coronelli) i gravure.',
    filter: {
      yearMin: 1400,
      yearMax: 1600,
      locations: ['ulcinj', 'stari_grad_ulcinj', 'valdanos', 'bar', 'skadar', 'venetian_albania'],
    },
    highlight:
      'Ulcinj je bio dio Mletačke Albanije od 1405. do otomanskog osvajanja 1571. Najbogatiji period za arhivsku građu — mletačka administracija dokumentovala je svaki aspekt: ekonomiju, fortifikacije, pomorstvo, gusarstvo, religiju.',
  },
  {
    slug: 'anticki-olcinium',
    title: 'Antički Olcinium',
    emoji: '🏛',
    description: 'Rimski natpisi i antičke lokacije Ulcinj-Skadar regiona iz EDH i Pelagios baza.',
    filter: {
      sources: ['edh', 'pelagios', 'wikidata'],
      locations: ['ulcinj', 'stari_grad_ulcinj', 'skadar', 'svac', 'drivast'],
    },
    highlight:
      'Olcinium se prvi put pominje kod Plinija Starijeg. Antičko ime Colchinium ukazuje na koloniju Kolhidana. Pod rimskom vlašću dobija status oppidum civium Romanorum.',
  },
  {
    slug: 'stari-ulcinj-kod-kruca',
    title: 'Stari Ulcinj kod Kruča (Dulcigno Vecchio)',
    emoji: '🏚',
    description: 'Ruševine srednjovjekovnog grada na obali kod Kruča, prvi pomen 1376. — zaseban grad od današnjeg Ulcinja.',
    filter: {
      locations: ['stari_ulcinj_kruce', 'kruce'],
    },
    highlight:
      'Mletački arhivi ga zovu Dulcigno Vecchio. Sadrži ostatke crkve XII-XIII vijeka. Lokalitet je manje istražen od glavnog Ulcinja — malo izvora, ali veliki istraživački potencijal.',
  },
  {
    slug: 'bojana-buna',
    title: 'Rijeka Bojana / Buna',
    emoji: '🌊',
    description: 'Ilirsko-rimsko-mletačka istorija glavne pomorske arterije Skadar–Jadran. Naziv kroz vrijeme: Barbanna → Barbana → Boiana → Bojana.',
    filter: {
      locations: ['bojana_buna', 'ada_bojana'],
    },
    highlight:
      'Bojana je istorijski glavni izlaz Skadarskog jezera na Jadran. Ime ima ilirske korijene (Barbanna), latinski oblik je Barbana, mletački Boiana. Ovde su se preko vekova ukrštali interesi Ilira, Rimljana, Vizantije, srpskih vladara, Mletaka, Otomana.',
  },
  {
    slug: 'svac-srednji-vijek',
    title: 'Svač — srednjovjekovna episkopija',
    emoji: '⛪',
    description: 'Civitas Suacensis, srednjovjekovna katolička episkopija sjeveroistočno od Ulcinja, danas ruševine kod Šasa.',
    filter: {
      locations: ['svac'],
    },
    highlight:
      'Svač je bio važan crkveni i administrativni centar Zete u srednjem vijeku. Episkopija je dokumentovana papskom korespondencijom. Danas potpuno napušten — ostaci zidina, bazilika, manje crkve.',
  },
  {
    slug: 'pomorstvo-jadran',
    title: 'Pomorstvo i jadranska trgovina',
    emoji: '⛵',
    description: 'Ulcinj kao pomorska sila — gusari Dulcignotti, mletačke trgovačke veze, brodovi, solane.',
    filter: {
      qLike: ['Dulcignotti', 'pirate', 'corsari', 'naval', 'Adriatic'],
    },
    highlight:
      'Ulcinj je u XV-XVII vijeku bio centar pomorstva — i mletačke trgovine i otomansko-doba gusarstva. Dulcignotti su bili poznati po brzim brigantinima i napadima na hrišćanske trgovačke brodove.',
  },
  {
    slug: 'mletacke-karte',
    title: 'Mletačke karte i gravire',
    emoji: '🗺',
    description: 'Camocio (1571), Coronelli (1688), Franco i drugi venecijanski kartografi koji su mapirali Ulcinj i jadransku obalu.',
    filter: {
      sources: ['europeana'],
      qLike: ['Camocio', 'Coronelli', 'mappa', 'carta'],
    },
    highlight:
      'Mletački kartografi XVI-XVIII vijeka producirali su najbogatiji vizuelni zapis Ulcinja. Ove karte su sad digitalizovane preko Europeane i dostupne u IIIF zoom kvalitetu kroz naš Mirador viewer.',
  },
];

export const COLLECTIONS_BY_SLUG = Object.fromEntries(COLLECTIONS.map((c) => [c.slug, c]));
