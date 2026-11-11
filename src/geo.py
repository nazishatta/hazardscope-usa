"""United States regions and geographic helpers; coordinates are approximate map centers."""
STATES = {
'AL':('Alabama',32.81,-86.79),'AK':('Alaska',64.20,-153.49),'AZ':('Arizona',34.27,-111.66),'AR':('Arkansas',34.89,-92.44),
'CA':('California',36.78,-119.42),'CO':('Colorado',39.00,-105.55),'CT':('Connecticut',41.60,-72.70),'DE':('Delaware',39.15,-75.52),
'FL':('Florida',27.66,-81.52),'GA':('Georgia',32.16,-82.90),'HI':('Hawaii',19.90,-155.58),'ID':('Idaho',44.07,-114.74),
'IL':('Illinois',40.63,-89.40),'IN':('Indiana',40.27,-86.13),'IA':('Iowa',42.03,-93.58),'KS':('Kansas',38.50,-98.00),
'KY':('Kentucky',37.84,-84.27),'LA':('Louisiana',31.17,-91.87),'ME':('Maine',45.25,-69.45),'MD':('Maryland',39.04,-76.64),
'MA':('Massachusetts',42.41,-71.38),'MI':('Michigan',44.31,-85.60),'MN':('Minnesota',46.73,-94.69),'MS':('Mississippi',32.35,-89.40),
'MO':('Missouri',38.46,-92.29),'MT':('Montana',46.88,-110.36),'NE':('Nebraska',41.49,-99.90),'NV':('Nevada',38.80,-116.42),
'NH':('New Hampshire',43.19,-71.57),'NJ':('New Jersey',40.06,-74.41),'NM':('New Mexico',34.52,-105.87),'NY':('New York',42.16,-74.95),
'NC':('North Carolina',35.76,-79.02),'ND':('North Dakota',47.55,-101.00),'OH':('Ohio',40.42,-82.91),'OK':('Oklahoma',35.47,-97.52),
'OR':('Oregon',43.80,-120.55),'PA':('Pennsylvania',41.20,-77.19),'RI':('Rhode Island',41.58,-71.48),'SC':('South Carolina',33.84,-81.16),
'SD':('South Dakota',43.97,-99.90),'TN':('Tennessee',35.52,-86.58),'TX':('Texas',31.05,-99.90),'UT':('Utah',39.32,-111.09),
'VT':('Vermont',44.56,-72.58),'VA':('Virginia',37.43,-78.66),'WA':('Washington',47.75,-120.74),'WV':('West Virginia',38.60,-80.45),
'WI':('Wisconsin',43.78,-88.79),'WY':('Wyoming',43.08,-107.29),'DC':('District of Columbia',38.91,-77.04),
'PR':('Puerto Rico',18.22,-66.59),'GU':('Guam',13.44,144.79),'VI':('U.S. Virgin Islands',18.34,-64.90),
'AS':('American Samoa',-14.27,-170.70),'MP':('Northern Mariana Islands',15.10,145.67)}
STATE_CODES = sorted(STATES, key=lambda code: STATES[code][0])
LOWER48 = set(STATES)-{'AK','HI','PR','GU','VI','AS','MP'}

def state_name(code):
    return STATES[code][0] if code in STATES else code

def center_for(code):
    if code in STATES:
        return STATES[code][1:]
    return (39.0,-98.0)

def bounds_for(code):
    """Coarse bounding boxes for visualization, not legally accurate state boundaries."""
    if code == 'US':
        return (25.0,49.0,-124.0,-67.0)
    lat,lon = center_for(code)
    if code=='AK':return (51,72,-170,-129)
    if code=='HI':return (18,23,-161,-154)
    if code in {'TX','CA','MT'}:return (lat-5,lat+5,lon-7,lon+7)
    return (lat-3.5,lat+3.5,lon-5.5,lon+5.5)
