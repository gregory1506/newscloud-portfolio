from enum import Enum

class Region(Enum):
    TT = "TT"
    UK = "UK"
    US_AK = "US-AK"
    US_AL = "US-AL"
    US_AR = "US-AR"
    US_AZ = "US-AZ"
    US_CA = "US-CA"
    US_CO = "US-CO"
    US_CT = "US-CT"
    US_DC = "US-DC"
    US_DE = "US-DE"
    US_FL = "US-FL"
    US_GA = "US-GA"
    US_HI = "US-HI"
    US_IA = "US-IA"
    US_ID = "US-ID"
    US_IL = "US-IL"
    US_IN = "US-IN"
    US_KS = "US-KS"
    US_KY = "US-KY"
    US_LA = "US-LA"
    US_MA = "US-MA"
    US_MD = "US-MD"
    US_ME = "US-ME"
    US_MI = "US-MI"
    US_MN = "US-MN"
    US_MO = "US-MO"
    US_MS = "US-MS"
    US_MT = "US-MT"
    US_NC = "US-NC"
    US_ND = "US-ND"
    US_NE = "US-NE"
    US_NH = "US-NH"
    US_NJ = "US-NJ"
    US_NM = "US-NM"
    US_NV = "US-NV"
    US_NY = "US-NY"
    US_OH = "US-OH"
    US_OK = "US-OK"
    US_OR = "US-OR"
    US_PA = "US-PA"
    US_RI = "US-RI"
    US_SC = "US-SC"
    US_SD = "US-SD"
    US_TN = "US-TN"
    US_TX = "US-TX"
    US_UT = "US-UT"
    US_VA = "US-VA"
    US_VT = "US-VT"
    US_WA = "US-WA"
    US_WI = "US-WI"
    US_WV = "US-WV"
    US_WY = "US-WY"


REGION_CANONICAL_NAMES = {
    Region.TT: "trinidad and tobago",
    Region.UK: "united kingdom britain",
    Region.US_AK: "alaska",
    Region.US_AL: "alabama",
    Region.US_AR: "arkansas",
    Region.US_AZ: "arizona",
    Region.US_CA: "california",
    Region.US_CO: "colorado",
    Region.US_CT: "connecticut",
    Region.US_DC: "district of columbia",
    Region.US_DE: "delaware",
    Region.US_FL: "florida",
    Region.US_GA: "georgia",
    Region.US_HI: "hawaii",
    Region.US_IA: "iowa",
    Region.US_ID: "idaho",
    Region.US_IL: "illinois",
    Region.US_IN: "indiana",
    Region.US_KS: "kansas",
    Region.US_KY: "kentucky",
    Region.US_LA: "louisiana",
    Region.US_MA: "massachusetts",
    Region.US_MD: "maryland",
    Region.US_ME: "maine",
    Region.US_MI: "michigan",
    Region.US_MN: "minnesota",
    Region.US_MO: "missouri",
    Region.US_MS: "mississippi",
    Region.US_MT: "montana",
    Region.US_NC: "north carolina",
    Region.US_ND: "north dakota",
    Region.US_NE: "nebraska",
    Region.US_NH: "new hampshire",
    Region.US_NJ: "new jersey",
    Region.US_NM: "new mexico",
    Region.US_NV: "nevada",
    Region.US_NY: "new york",
    Region.US_OH: "ohio",
    Region.US_OK: "oklahoma",
    Region.US_OR: "oregon",
    Region.US_PA: "pennsylvania",
    Region.US_RI: "rhode island",
    Region.US_SC: "south carolina",
    Region.US_SD: "south dakota",
    Region.US_TN: "tennessee",
    Region.US_TX: "texas",
    Region.US_UT: "utah",
    Region.US_VA: "virginia",
    Region.US_VT: "vermont",
    Region.US_WA: "washington",
    Region.US_WI: "wisconsin",
    Region.US_WV: "west virginia",
    Region.US_WY: "wyoming",
}

REGION_DISPLAY_NAME_OVERRIDES = {
    Region.TT: "Trinidad and Tobago",
    Region.UK: "United Kingdom",
    Region.US_DC: "District of Columbia",
}

REGION_SOURCES = {
    Region.TT: [
        {"name": "CNC3", "type": "rss", "url": "https://www.cnc3.co.tt/feed/"},
        {
            "name": "Trinidad Express",
            "type": "rss",
            "url": "https://trinidadexpress.com/search/?f=rss&t=article&l=50&s=start_time&sd=desc",
            # The broad TownNews feed also carries paid global press releases,
            # which are not Trinidad news and can overwhelm ordinary terms.
            "exclude_url_patterns": ["/online_features/press_releases/"],
        },
        {"name": "TTT Live", "type": "rss", "url": "https://www.ttt.live/feed/"},
        {"name": "Trinidad Guardian", "type": "rss", "url": "https://news.google.com/rss/search?q=site:guardian.co.tt&hl=en-TT&gl=TT&ceid=TT:en"},
        {"name": "Wired868", "type": "rss", "url": "https://news.google.com/rss/search?q=site:wired868.com&hl=en-TT&gl=TT&ceid=TT:en"}
    ],
    Region.UK: [
        {"name": "BBC UK", "type": "rss", "url": "http://feeds.bbci.co.uk/news/uk/rss.xml"},
        {"name": "The Guardian", "type": "rss", "url": "https://www.theguardian.com/uk/rss"},
        {"name": "Sky News", "type": "rss", "url": "https://feeds.skynews.com/feeds/rss/uk.xml"},
        {"name": "The Independent", "type": "rss", "url": "https://www.independent.co.uk/news/uk/rss"}
    ],
    Region.US_AK: [
        {"name": "Local News AK", "type": "rss", "url": "https://www.adn.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Alaska Beacon", "type": "rss", "url": "https://alaskabeacon.com/feed/"},
        {"name": "Google News AK", "type": "rss", "url": "https://news.google.com/rss/search?q=Alaska+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News AK Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Alaska+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_AL: [
        {"name": "Alabama Reflector", "type": "rss", "url": "https://alabamareflector.com/feed/"},
        {"name": "Google News AL", "type": "rss", "url": "https://news.google.com/rss/search?q=Alabama+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News AL Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Alabama+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_AR: [
        {"name": "Local News AR", "type": "rss", "url": "https://www.kark.com/feed/"},
        {"name": "Arkansas Advocate", "type": "rss", "url": "https://arkansasadvocate.com/feed/"},
        {"name": "Google News AR", "type": "rss", "url": "https://news.google.com/rss/search?q=Arkansas+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News AR Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Arkansas+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_AZ: [
        {"name": "Local News AZ", "type": "rss", "url": "https://www.12news.com/feeds/syndication/rss/news/local"},
        {"name": "Google News AZ", "type": "rss", "url": "https://news.google.com/rss/search?q=Arizona+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Arizona Mirror", "type": "rss", "url": "https://azmirror.com/feed/"},
        {"name": "Google News AZ Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Arizona+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_CA: [
        {"name": "LA Times", "type": "rss", "url": "https://www.latimes.com/california/rss2.0.xml"},
        {"name": "KTLA 5", "type": "rss", "url": "https://ktla.com/feed/"}
    ],
    Region.US_CO: [
        {"name": "Local News CO", "type": "rss", "url": "https://www.9news.com/feeds/syndication/rss/news/local"},
        {"name": "Colorado Sun", "type": "rss", "url": "https://coloradosun.com/feed/"},
        {"name": "Google News CO", "type": "rss", "url": "https://news.google.com/rss/search?q=Colorado+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News CO Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Colorado+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_CT: [
        {"name": "Local News CT", "type": "rss", "url": "https://www.wtnh.com/feed/"},
        {"name": "CT Mirror", "type": "rss", "url": "https://ctmirror.org/feed/"},
        {"name": "CT News Junkie", "type": "rss", "url": "https://ctnewsjunkie.com/feed/"},
        {"name": "Google News CT", "type": "rss", "url": "https://news.google.com/rss/search?q=Connecticut+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News CT Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Connecticut+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_DC: [
        {"name": "Local News DC", "type": "rss", "url": "https://www.wusa9.com/feeds/syndication/rss/news/local"},
        {"name": "WAMU 88.5", "type": "rss", "url": "https://wamu.org/feed"},
        {"name": "The DC Line", "type": "rss", "url": "https://thedcline.org/feed/"},
        {"name": "Google News DC", "type": "rss", "url": "https://news.google.com/rss/search?q=Washington+DC+local+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News DC Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Washington+DC+politics+city+council+legislation&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_DE: [
        {"name": "Delaware Online", "type": "rss", "url": "https://www.delawareonline.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Local News DE", "type": "rss", "url": "https://www.wdel.com/search/?f=rss&t=article&c=news/local&l=50&s=start_time&sd=desc"},
        {"name": "Spotlight Delaware", "type": "rss", "url": "https://spotlightdelaware.org/feed/"},
        {"name": "Delaware Public Media", "type": "rss", "url": "https://www.delawarepublic.org/rss/news.xml"},
        {"name": "Google News DE", "type": "rss", "url": "https://news.google.com/rss/search?q=Delaware+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News DE Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Delaware+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_FL: [
        {"name": "Local News FL", "type": "rss", "url": "https://floridapolitics.com/feed/"},
        {"name": "Florida Phoenix", "type": "rss", "url": "https://floridaphoenix.com/feed/"},
        {"name": "Google News FL", "type": "rss", "url": "https://news.google.com/rss/search?q=Florida+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News FL Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Florida+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_GA: [
        {"name": "Local News GA", "type": "rss", "url": "https://www.11alive.com/feeds/syndication/rss/news/local"},
        {"name": "Google News GA", "type": "rss", "url": "https://news.google.com/rss/search?q=Georgia+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Georgia Recorder", "type": "rss", "url": "https://georgiarecorder.com/feed/"},
        {"name": "Google News GA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Georgia+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_HI: [
        {"name": "Local News HI", "type": "rss", "url": "https://www.hawaiitribune-herald.com/feed/"},
        {"name": "Civil Beat", "type": "rss", "url": "https://civilbeat.org/feed/"},
        {"name": "Google News HI", "type": "rss", "url": "https://news.google.com/rss/search?q=Hawaii+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News HI Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Hawaii+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_IA: [
        {"name": "Local News IA", "type": "rss", "url": "https://www.kcci.com/topstories-rss"},
        {"name": "Iowa Capital Dispatch", "type": "rss", "url": "https://iowacapitaldispatch.com/feed/"},
        {"name": "Google News IA", "type": "rss", "url": "https://news.google.com/rss/search?q=Iowa+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News IA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Iowa+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_ID: [
        {"name": "Local News ID", "type": "rss", "url": "https://www.ktvb.com/feeds/syndication/rss/news/local"},
        {"name": "Idaho Capital Sun", "type": "rss", "url": "https://idahocapitalsun.com/feed/"},
        {"name": "Boise State Public Radio", "type": "rss", "url": "https://www.boisestatepublicradio.org/rss/news.xml"},
        {"name": "Google News ID", "type": "rss", "url": "https://news.google.com/rss/search?q=Idaho+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News ID Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Idaho+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_IL: [
        {"name": "Local News IL", "type": "rss", "url": "https://abc7chicago.com/feed/"},
        {"name": "Capitol News Illinois", "type": "rss", "url": "https://capitolnewsillinois.com/feed/"},
        {"name": "Google News IL", "type": "rss", "url": "https://news.google.com/rss/search?q=Illinois+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News IL Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Illinois+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_IN: [
        {"name": "Local News IN", "type": "rss", "url": "https://www.wthr.com/feeds/syndication/rss/news/local"},
        {"name": "Indiana Capital Chronicle", "type": "rss", "url": "https://indianacapitalchronicle.com/feed/"},
        {"name": "Google News IN", "type": "rss", "url": "https://news.google.com/rss/search?q=Indiana+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News IN Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Indiana+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_KS: [
        {"name": "Local News KS", "type": "rss", "url": "https://www.ksnt.com/feed/"},
        {"name": "Kansas Reflector", "type": "rss", "url": "https://kansasreflector.com/feed/"},
        {"name": "Google News KS", "type": "rss", "url": "https://news.google.com/rss/search?q=Kansas+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News KS Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Kansas+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_KY: [
        {"name": "Local News KY", "type": "rss", "url": "https://www.whas11.com/feeds/syndication/rss/news/local"},
        {"name": "Kentucky Lantern", "type": "rss", "url": "https://kentuckylantern.com/feed/"},
        {"name": "Google News KY", "type": "rss", "url": "https://news.google.com/rss/search?q=Kentucky+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News KY Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Kentucky+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_LA: [
        {"name": "Local News LA", "type": "rss", "url": "https://www.theadvocate.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
        {"name": "Louisiana Illuminator", "type": "rss", "url": "https://lailluminator.com/feed/"},
        {"name": "Google News LA", "type": "rss", "url": "https://news.google.com/rss/search?q=Louisiana+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News LA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Louisiana+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MA: [
        {"name": "Local News MA", "type": "rss", "url": "https://www.wcvb.com/topstories-rss"},
        {"name": "CommonWealth Beacon", "type": "rss", "url": "https://commonwealthbeacon.org/feed/"},
        {"name": "Google News MA", "type": "rss", "url": "https://news.google.com/rss/search?q=Massachusetts+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Massachusetts+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MD: [
        {"name": "Local News MD", "type": "rss", "url": "https://www.wbaltv.com/topstories-rss"},
        {"name": "Maryland Matters", "type": "rss", "url": "https://marylandmatters.org/feed/"},
        {"name": "Google News MD", "type": "rss", "url": "https://news.google.com/rss/search?q=Maryland+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MD Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Maryland+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_ME: [
        {"name": "Local News ME", "type": "rss", "url": "https://www.wmtw.com/topstories-rss"},
        {"name": "Portland Press Herald", "type": "rss", "url": "https://www.pressherald.com/feed/"},
        {"name": "Google News ME", "type": "rss", "url": "https://news.google.com/rss/search?q=Maine+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News ME Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Maine+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MI: [
        {"name": "Local News MI", "type": "rss", "url": "https://www.mlive.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Google News MI", "type": "rss", "url": "https://news.google.com/rss/search?q=Michigan+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Michigan Advance", "type": "rss", "url": "https://michiganadvance.com/feed/"},
        {"name": "Google News MI Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Michigan+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MN: [
        {"name": "Local News MN", "type": "rss", "url": "https://www.kare11.com/feeds/syndication/rss/news/local"},
        {"name": "Minnesota Reformer", "type": "rss", "url": "https://minnesotareformer.com/feed/"},
        {"name": "MinnPost", "type": "rss", "url": "https://www.minnpost.com/feed/"},
        {"name": "Google News MN", "type": "rss", "url": "https://news.google.com/rss/search?q=Minnesota+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MN Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Minnesota+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MO: [
        {"name": "Local News MO", "type": "rss", "url": "https://www.ksdk.com/feeds/syndication/rss/news/local"},
        {"name": "Missouri Independent", "type": "rss", "url": "https://missouriindependent.com/feed/"},
        {"name": "Google News MO", "type": "rss", "url": "https://news.google.com/rss/search?q=Missouri+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MO Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Missouri+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MS: [
        {"name": "Local News MS", "type": "rss", "url": "https://www.wapt.com/topstories-rss"},
        {"name": "Mississippi Today", "type": "rss", "url": "https://mississippitoday.org/feed/"},
        {"name": "Google News MS", "type": "rss", "url": "https://news.google.com/rss/search?q=Mississippi+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MS Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Mississippi+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_MT: [
        {"name": "Montana Free Press", "type": "rss", "url": "https://montanafreepress.org/feed/"},
        {"name": "Missoula Current", "type": "rss", "url": "https://missoulacurrent.com/feed/"},
        {"name": "Google News MT", "type": "rss", "url": "https://news.google.com/rss/search?q=Montana+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News MT Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Montana+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NC: [
        {"name": "Local News NC", "type": "rss", "url": "https://www.wcnc.com/feeds/syndication/rss/news/local"},
        {"name": "Google News NC", "type": "rss", "url": "https://news.google.com/rss/search?q=North+Carolina+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "NC Newsline", "type": "rss", "url": "https://ncnewsline.com/feed/"},
        {"name": "Google News NC Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=North+Carolina+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_ND: [
        {"name": "Local News ND", "type": "rss", "url": "https://bismarcktribune.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
        {"name": "North Dakota Monitor", "type": "rss", "url": "https://northdakotamonitor.com/feed/"},
        {"name": "Google News ND", "type": "rss", "url": "https://news.google.com/rss/search?q=North+Dakota+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News ND Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=North+Dakota+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NE: [
        {"name": "Local News NE", "type": "rss", "url": "https://www.ketv.com/topstories-rss"},
        {"name": "Nebraska Examiner", "type": "rss", "url": "https://nebraskaexaminer.com/feed/"},
        {"name": "Google News NE", "type": "rss", "url": "https://news.google.com/rss/search?q=Nebraska+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News NE Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Nebraska+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NH: [
        {"name": "Local News NH", "type": "rss", "url": "https://www.wmur.com/topstories-rss"},
        {"name": "NHPR", "type": "rss", "url": "https://www.nhpr.org/rss.xml"},
        {"name": "New Hampshire Bulletin", "type": "rss", "url": "https://newhampshirebulletin.com/feed/"},
        {"name": "Google News NH", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Hampshire+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News NH Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Hampshire+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NJ: [
        {"name": "Local News NJ", "type": "rss", "url": "https://www.nj.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "New Jersey Monitor", "type": "rss", "url": "https://newjerseymonitor.com/feed/"},
        {"name": "Google News NJ", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Jersey+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News NJ Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Jersey+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NM: [
        {"name": "Local News NM", "type": "rss", "url": "https://www.koat.com/topstories-rss"},
        {"name": "Source New Mexico", "type": "rss", "url": "https://sourcenm.com/feed/"},
        {"name": "Google News NM", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Mexico+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News NM Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=New+Mexico+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NV: [
        {"name": "Local News NV", "type": "rss", "url": "https://www.ktnv.com/news/rss"},
        {"name": "Google News NV", "type": "rss", "url": "https://news.google.com/rss/search?q=Nevada+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Nevada Current", "type": "rss", "url": "https://nevadacurrent.com/feed/"},
        {"name": "The Nevada Independent", "type": "rss", "url": "https://thenevadaindependent.com/feed/"},
        {"name": "Google News NV Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Nevada+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_NY: [
        {"name": "New York Times", "type": "rss", "url": "https://rss.nytimes.com/services/xml/rss/nyt/NYRegion.xml"},
        {"name": "New York Post", "type": "rss", "url": "https://nypost.com/metro/feed/"},
        {"name": "ABC7 NY", "type": "rss", "url": "https://abc7ny.com/feed/"}
    ],
    Region.US_OH: [
        {"name": "Local News OH", "type": "rss", "url": "https://fox8.com/feed/"},
        {"name": "Ohio Capital Journal", "type": "rss", "url": "https://ohiocapitaljournal.com/feed/"},
        {"name": "Statehouse News Bureau", "type": "rss", "url": "https://www.statenews.org/rss/news.xml"},
        {"name": "Google News OH", "type": "rss", "url": "https://news.google.com/rss/search?q=Ohio+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News OH Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Ohio+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_OK: [
        {"name": "Local News OK", "type": "rss", "url": "https://www.koco.com/topstories-rss"},
        {"name": "Oklahoma Voice", "type": "rss", "url": "https://oklahomavoice.com/feed/"},
        {"name": "Google News OK", "type": "rss", "url": "https://news.google.com/rss/search?q=Oklahoma+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News OK Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Oklahoma+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_OR: [
        {"name": "Local News OR", "type": "rss", "url": "https://www.kgw.com/feeds/syndication/rss/news/local"},
        {"name": "Oregon Capital Chronicle", "type": "rss", "url": "https://oregoncapitalchronicle.com/feed/"},
        {"name": "Google News OR", "type": "rss", "url": "https://news.google.com/rss/search?q=Oregon+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News OR Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Oregon+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_PA: [
        {"name": "Local News PA", "type": "rss", "url": "https://6abc.com/feed/"},
        {"name": "Google News PA", "type": "rss", "url": "https://news.google.com/rss/search?q=Pennsylvania+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Pennsylvania Capital-Star", "type": "rss", "url": "https://penncapital-star.com/feed/"},
        {"name": "Google News PA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Pennsylvania+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_RI: [
        {"name": "Local News RI", "type": "rss", "url": "https://www.wpri.com/feed/"},
        {"name": "Rhode Island Current", "type": "rss", "url": "https://rhodeislandcurrent.com/feed/"},
        {"name": "Google News RI", "type": "rss", "url": "https://news.google.com/rss/search?q=Rhode+Island+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News RI Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Rhode+Island+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_SC: [
        {"name": "Local News SC", "type": "rss", "url": "https://www.wltx.com/feeds/syndication/rss/news/local"},
        {"name": "Post and Courier", "type": "rss", "url": "https://www.postandcourier.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
        {"name": "Google News SC", "type": "rss", "url": "https://news.google.com/rss/search?q=South+Carolina+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News SC Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=South+Carolina+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_SD: [
        {"name": "Local News SD", "type": "rss", "url": "https://www.keloland.com/feed/"},
        {"name": "South Dakota Searchlight", "type": "rss", "url": "https://southdakotasearchlight.com/feed/"},
        {"name": "Google News SD", "type": "rss", "url": "https://news.google.com/rss/search?q=South+Dakota+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News SD Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=South+Dakota+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_TN: [
        {"name": "Local News TN", "type": "rss", "url": "https://www.wkrn.com/feed/"},
        {"name": "Tennessee Lookout", "type": "rss", "url": "https://tennesseelookout.com/feed/"},
        {"name": "Google News TN", "type": "rss", "url": "https://news.google.com/rss/search?q=Tennessee+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News TN Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Tennessee+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_TX: [
        {"name": "Local News TX", "type": "rss", "url": "https://www.texastribune.org/feeds/main/"},
        {"name": "Texas Observer", "type": "rss", "url": "https://www.texasobserver.org/feed/"},
        {"name": "Google News TX", "type": "rss", "url": "https://news.google.com/rss/search?q=Texas+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News TX Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Texas+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_UT: [
        {"name": "Local News UT", "type": "rss", "url": "https://www.ksl.com/rss/news"},
        {"name": "Utah News Dispatch", "type": "rss", "url": "https://utahnewsdispatch.com/feed/"},
        {"name": "Salt Lake Tribune", "type": "rss", "url": "https://www.sltrib.com/arc/outboundfeeds/rss/"},
        {"name": "Google News UT", "type": "rss", "url": "https://news.google.com/rss/search?q=Utah+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News UT Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Utah+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_VA: [
        {"name": "Local News VA", "type": "rss", "url": "https://www.wavy.com/feed/"},
        {"name": "Virginia Mercury", "type": "rss", "url": "https://virginiamercury.com/feed/"},
        {"name": "Google News VA", "type": "rss", "url": "https://news.google.com/rss/search?q=Virginia+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News VA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Virginia+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_VT: [
        {"name": "VTDigger", "type": "rss", "url": "https://vtdigger.org/feed/"},
        {"name": "Seven Days Vermont", "type": "rss", "url": "https://www.sevendaysvt.com/vermont/Rss.xml"},
        {"name": "Google News VT", "type": "rss", "url": "https://news.google.com/rss/search?q=Vermont+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News VT Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Vermont+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_WA: [
        {"name": "Local News WA", "type": "rss", "url": "https://www.king5.com/feeds/syndication/rss/news/local"},
        {"name": "Washington State Standard", "type": "rss", "url": "https://washingtonstatestandard.com/feed/"},
        {"name": "Google News WA", "type": "rss", "url": "https://news.google.com/rss/search?q=Washington+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News WA Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Washington+state+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_WI: [
        {"name": "Local News WI", "type": "rss", "url": "https://www.wisn.com/topstories-rss"},
        {"name": "Google News WI", "type": "rss", "url": "https://news.google.com/rss/search?q=Wisconsin+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Wisconsin Examiner", "type": "rss", "url": "https://wisconsinexaminer.com/feed/"},
        {"name": "Google News WI Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=Wisconsin+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_WV: [
        {"name": "Local News WV", "type": "rss", "url": "https://www.wtrf.com/feed/"},
        {"name": "Mountain State Spotlight", "type": "rss", "url": "https://mountainstatespotlight.org/feed/"},
        {"name": "Google News WV", "type": "rss", "url": "https://news.google.com/rss/search?q=West+Virginia+state+news+politics&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Google News WV Politics", "type": "rss", "url": "https://news.google.com/rss/search?q=West+Virginia+politics+election+legislature&hl=en-US&gl=US&ceid=US:en"}
    ],
    Region.US_WY: [
        {"name": "WyoFile", "type": "rss", "url": "https://wyofile.com/feed/"},
        {"name": "Oil City WY", "type": "rss", "url": "https://oilcitywyo.com/feed/"},
        {"name": "Casper Star-Tribune", "type": "rss", "url": "https://trib.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
        {"name": "Local News WY", "type": "rss", "url": "https://www.kgwn.tv/feed/"},
        {"name": "Google News WY", "type": "rss", "url": "https://news.google.com/rss/search?q=Wyoming+state+news+politics&hl=en-US&gl=US&ceid=US:en"}
    ],
}

REGION_STOP_TERM_CONFIGS = {
    Region.TT: {
        "version": "tt-v3",
        "terms": {
            "apr",
            "april",
            "aug",
            "august",
            "dec",
            "december",
            "feb",
            "february",
            "friday",
            "jan",
            "january",
            "jul",
            "july",
            "jun",
            "june",
            "mar",
            "march",
            "monday",
            "nov",
            "november",
            "oct",
            "october",
            "saturday",
            "sep",
            "sept",
            "september",
            "sunday",
            "thursday",
            "trinidadian",
            "trinidadians",
            "tuesday",
            "tobagonian",
            "tobagonians",
            "wednesday",
        },
    },
    Region.US_DC: {
        "version": "us-dc-v1",
        "terms": {"washington"},
    },
}

REGION_NEWDATA_QUERY_OVERRIDES = {
    Region.US_AL: "Alabama politics news",
    Region.US_AR: "Arkansas politics news",
    Region.US_CO: "Colorado politics news",
    Region.US_CT: "Connecticut politics news",
    Region.US_HI: "Hawaii politics news",
    Region.US_IA: "Iowa politics news",
    Region.US_ID: "Idaho politics news",
    Region.US_IN: "Indiana politics news",
    Region.US_KS: "Kansas politics news",
    Region.US_KY: "Kentucky politics news",
    Region.US_LA: "Louisiana politics news",
    Region.US_MD: "Maryland politics news",
    Region.US_ME: "Maine politics news",
    Region.US_MN: "Minnesota politics news",
    Region.US_MO: "Missouri politics news",
    Region.US_MS: "Mississippi politics news",
    Region.US_MT: "Montana politics news",
    Region.US_ND: "North Dakota politics news",
    Region.US_NE: "Nebraska politics news",
    Region.US_NH: "New Hampshire politics news",
    Region.US_NJ: "New Jersey politics news",
    Region.US_NM: "New Mexico politics news",
    Region.US_OH: "Ohio politics news",
    Region.US_OK: "Oklahoma politics news",
    Region.US_OR: "Oregon politics news",
    Region.US_RI: "Rhode Island politics news",
    Region.US_SC: "South Carolina politics news",
    Region.US_SD: "South Dakota politics news",
    Region.US_TN: "Tennessee politics news",
    Region.US_UT: "Utah politics news",
    Region.US_VA: "Virginia politics news",
    Region.US_VT: "Vermont politics news",
    Region.US_WA: "Washington state politics news",
    Region.US_WV: "West Virginia politics news",
}


def get_sources_for_region(region: Region):
    sources = list(REGION_SOURCES.get(region, []))
    sources.extend(get_newsdata_sources_for_region(region))
    return sources


def get_region_canonical_name(region: Region):
    return REGION_CANONICAL_NAMES.get(region, region.value.lower())


def get_region_display_name(region: Region):
    override = REGION_DISPLAY_NAME_OVERRIDES.get(region)
    if override:
        return override
    return get_region_canonical_name(region).title()


def get_region_stop_tokens(region: Region):
    return set(get_region_canonical_name(region).split())


def get_region_country_code(region: Region):
    if region == Region.TT:
        return "TT"
    if region == Region.UK:
        return "GB"
    return "US"


def get_region_search_language(region: Region):
    return "en"


def get_newsdata_sources_for_region(region: Region):
    display_name = get_region_display_name(region)
    if region == Region.TT:
        broad_query = "Trinidad and Tobago news"
    elif region == Region.UK:
        broad_query = "United Kingdom news"
    elif region == Region.US_DC:
        broad_query = "District of Columbia news"
    else:
        broad_query = f"{display_name} state news"

    broad_query = REGION_NEWDATA_QUERY_OVERRIDES.get(region, broad_query)

    sources = [{
        "name": "NewsData.io",
        "type": "newsdata_io",
        "query": broad_query,
        "country": get_region_country_code(region),
        "language": get_region_search_language(region),
    }]

    return sources

def get_extra_stop_words_for_region(region: Region):
    config = REGION_STOP_TERM_CONFIGS.get(region, {})
    return set(config.get("terms", set()))


def get_region_stop_term_version(region: Region):
    config = REGION_STOP_TERM_CONFIGS.get(region, {})
    return config.get("version", "default-v1")
