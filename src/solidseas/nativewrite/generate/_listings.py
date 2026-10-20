"""The listings of section 15 (docs/sldprt-spec/listings), compiled into operations.

Written by scripts/compile-sldprt-spec.py; do not edit, run the script again.
Each operation is one line of a listing (generate/listing.py says how to read
them) and cites its section, file and line. MEMBERS is the member table of
section 15.0.1, in order: (member, section, listing).
"""

# ruff: noqa: E501

MEMBERS = (
    ('Contents/3DExperienceExchange2', '15.3', '3dexperience-exchange2.srl'),  # spec 15.0.1 3dexperience-exchange2.srl
    ('Contents/3DExperienceExchange_ConfigHeader', '15.3', '3dexperience-configheader.srl'),  # spec 15.0.1 3dexperience-configheader.srl
    ('Contents/CMgr', '15.2', 'cmgr.srl'),  # spec 15.0.1 cmgr.srl
    ('Contents/CMgrHdr2', '15.2', 'cmgrhdr2.srl'),  # spec 15.0.1 cmgrhdr2.srl
    ('Contents/CnfgObjs', '15.1', 'cnfgobjs.srl'),  # spec 15.0.1 cnfgobjs.srl
    ('Contents/Config-0', '15.4', 'config-0.srl'),  # spec 15.0.1 config-0.srl
    ('Contents/Config-0-LWDATA', '15.2', 'config-0-lwdata.srl'),  # spec 15.0.1 config-0-lwdata.srl
    ('Contents/Config-0-ModelHeader', '15.2', 'config-0-modelheader.srl'),  # spec 15.0.1 config-0-modelheader.srl
    ('Contents/Config-0-ResolvedFeatures', '15.5', 'config-0-resolvedfeatures.srl'),  # spec 15.0.1 config-0-resolvedfeatures.srl
    ('Contents/CusProps', '15.2', 'cusprops.srl'),  # spec 15.0.1 cusprops.srl
    ('Contents/Definition', '15.2', 'definition.srl'),  # spec 15.0.1 definition.srl
    ('Contents/OleItems', '15.1', 'oleitems.srl'),  # spec 15.0.1 oleitems.srl
    ('Contents/eModelLic', '15.1', 'emodellic.srl'),  # spec 15.0.1 emodellic.srl
    ('Header2', '15.2', 'header2.srl'),  # spec 15.0.1 header2.srl
    ('ModelStamps', '15.1', 'modelstamps.srl'),  # spec 15.0.1 modelstamps.srl
    ('OleItemInformation/OLE_Item_Data', '15.1', 'ole-item-data.srl'),  # spec 15.0.1 ole-item-data.srl
    ('SwDocContentMgr/SwDocContentMgrInfo', '15.1', 'swdoccontentmgrinfo.srl'),  # spec 15.0.1 swdoccontentmgrinfo.srl
    ('ThirdPty/Animator', '15.2', 'animator.srl'),  # spec 15.0.1 animator.srl
    ('ThirdPty/CMMotionLoadMapU', '15.1', 'cmmotionloadmapu.srl'),  # spec 15.0.1 cmmotionloadmapu.srl
    ('ThirdPty/CM_MOTION_LOAD_1', '15.1', 'cm-motion-load-1.srl'),  # spec 15.0.1 cm-motion-load-1.srl
    ('ThirdPty/SWA_Schedules', '15.1', 'swa-schedules.srl'),  # spec 15.0.1 swa-schedules.srl
    ('ThirdPtyStore/VisualStates', '15.2', 'visualstates.srl'),  # spec 15.0.1 visualstates.srl
    ('[Content_Types].xml', '15.1', 'content-types.srl'),  # spec 15.0.1 content-types.srl
    ('_DL_VERSION_17000/DLUpdateStamp', '15.1', 'dlupdatestamp.srl'),  # spec 15.0.1 dlupdatestamp.srl
    ('_MO_VERSION_17000/Biography', '15.2', 'biography.srl'),  # spec 15.0.1 biography.srl
    ('_MO_VERSION_17000/History', '15.1', 'history.srl'),  # spec 15.0.1 history.srl
    ('_rels/.rels', '15.1', 'rels.srl'),  # spec 15.0.1 rels.srl
    ('docProps/Config-0-Properties.xml', '15.1', 'config-0-properties.srl'),  # spec 15.0.1 config-0-properties.srl
    ('docProps/ISolidWorksInformation.xml', '15.1', 'isolidworksinformation.srl'),  # spec 15.0.1 isolidworksinformation.srl
    ('docProps/OpenTime.xml', '15.1', 'opentime.srl'),  # spec 15.0.1 opentime.srl
    ('docProps/app.xml', '15.1', 'app.srl'),  # spec 15.0.1 app.srl
    ('docProps/core.xml', '15.1', 'core.srl'),  # spec 15.0.1 core.srl
    ('docProps/custom.xml', '15.1', 'custom.srl'),  # spec 15.0.1 custom.srl
    ('swXmlContents/Features', '15.1', 'features-xml.srl'),  # spec 15.0.1 features-xml.srl
    ('swXmlContents/KeyWords', '15.1', 'keywords.srl'),  # spec 15.0.1 keywords.srl
)

LISTINGS = {
    'Contents/3DExperienceExchange2': (  # spec 15.3 3dexperience-exchange2.srl
        ('put', 'latin1', ('unqlite',), '15.3.2 3dexperience-exchange2.srl:6'),  # spec 15.3.2 3dexperience-exchange2.srl:6
        ('put', 'u32be', (3682346770,), '15.3.2 3dexperience-exchange2.srl:7'),  # spec 15.3.2 3dexperience-exchange2.srl:7
        ('put', 'u16be', (('=', '($exch.time.year-1980)*512+($exch.time.month-1)*32+$exch.time.day'),), '15.3.2 3dexperience-exchange2.srl:9'),  # spec 15.3.2 3dexperience-exchange2.srl:9
        ('put', 'u16be', (('=', '$exch.time.hour*2048+$exch.time.minute*32+$exch.time.second//2'),), '15.3.2 3dexperience-exchange2.srl:10'),  # spec 15.3.2 3dexperience-exchange2.srl:10
        ('put', 'u32be', (512,), '15.3.2 3dexperience-exchange2.srl:11'),  # spec 15.3.2 3dexperience-exchange2.srl:11
        ('put', 'u32be', (4096,), '15.3.2 3dexperience-exchange2.srl:12'),  # spec 15.3.2 3dexperience-exchange2.srl:12
        ('put', 'u16be', (4,), '15.3.2 3dexperience-exchange2.srl:13'),  # spec 15.3.2 3dexperience-exchange2.srl:13
        ('put', 'latin1', ('hash',), '15.3.2 3dexperience-exchange2.srl:14'),  # spec 15.3.2 3dexperience-exchange2.srl:14
        ('rep', 4067, 0, '15.3.2 3dexperience-exchange2.srl:15'),  # spec 15.3.2 3dexperience-exchange2.srl:15
        ('put', 'u32be', (4202180043,), '15.3.3 3dexperience-exchange2.srl:19'),  # spec 15.3.3 3dexperience-exchange2.srl:19
        ('put', 'u32be', (66397173,), '15.3.3 3dexperience-exchange2.srl:20'),  # spec 15.3.3 3dexperience-exchange2.srl:20
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:21'),  # spec 15.3.3 3dexperience-exchange2.srl:21
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:22'),  # spec 15.3.3 3dexperience-exchange2.srl:22
        ('put', 'u64be', (1,), '15.3.3 3dexperience-exchange2.srl:23'),  # spec 15.3.3 3dexperience-exchange2.srl:23
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:24'),  # spec 15.3.3 3dexperience-exchange2.srl:24
        ('put', 'u32be', (1,), '15.3.3 3dexperience-exchange2.srl:25'),  # spec 15.3.3 3dexperience-exchange2.srl:25
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:26'),  # spec 15.3.3 3dexperience-exchange2.srl:26
        ('put', 'u64be', (2,), '15.3.3 3dexperience-exchange2.srl:27'),  # spec 15.3.3 3dexperience-exchange2.srl:27
        ('rep', 4036, 0, '15.3.3 3dexperience-exchange2.srl:28'),  # spec 15.3.3 3dexperience-exchange2.srl:28
        ('put', 'u16be', (1708,), '15.3.4 3dexperience-exchange2.srl:42'),  # spec 15.3.4 3dexperience-exchange2.srl:42
        ('put', 'u16be', (1892,), '15.3.4 3dexperience-exchange2.srl:43'),  # spec 15.3.4 3dexperience-exchange2.srl:43
        ('put', 'u64be', (0,), '15.3.4 3dexperience-exchange2.srl:44'),  # spec 15.3.4 3dexperience-exchange2.srl:44
        ('put', 'u32be', (('$', 'exch.hash.front'),), '15.3.3 3dexperience-exchange2.srl:32'),  # spec 15.3.3 3dexperience-exchange2.srl:32
        ('put', 'u32be', (36,), '15.3.3 3dexperience-exchange2.srl:33'),  # spec 15.3.3 3dexperience-exchange2.srl:33
        ('put', 'u64be', (399,), '15.3.3 3dexperience-exchange2.srl:34'),  # spec 15.3.3 3dexperience-exchange2.srl:34
        ('put', 'u16be', (0,), '15.3.3 3dexperience-exchange2.srl:35'),  # spec 15.3.3 3dexperience-exchange2.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:36'),  # spec 15.3.3 3dexperience-exchange2.srl:36
        ('put', 'utf8', (('$', 'exch.front'),), '15.3.5 3dexperience-exchange2.srl:49'),  # spec 15.3.5 3dexperience-exchange2.srl:49
        ('put', 'u8', (143,), '15.3.5 3dexperience-exchange2.srl:50'),  # spec 15.3.5 3dexperience-exchange2.srl:50
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:51'),  # spec 15.3.5 3dexperience-exchange2.srl:51
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:52'),  # spec 15.3.5 3dexperience-exchange2.srl:52
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:53'),  # spec 15.3.5 3dexperience-exchange2.srl:53
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:54'),  # spec 15.3.5 3dexperience-exchange2.srl:54
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:55'),  # spec 15.3.5 3dexperience-exchange2.srl:55
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:56'),  # spec 15.3.5 3dexperience-exchange2.srl:56
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:57'),  # spec 15.3.5 3dexperience-exchange2.srl:57
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:58'),  # spec 15.3.5 3dexperience-exchange2.srl:58
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:59'),  # spec 15.3.5 3dexperience-exchange2.srl:59
        ('put', 'utf8', ('description',), '15.3.5 3dexperience-exchange2.srl:60'),  # spec 15.3.5 3dexperience-exchange2.srl:60
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:61'),  # spec 15.3.5 3dexperience-exchange2.srl:61
        ('put', 'utf8', ('Front Plane',), '15.3.5 3dexperience-exchange2.srl:62'),  # spec 15.3.5 3dexperience-exchange2.srl:62
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:63'),  # spec 15.3.5 3dexperience-exchange2.srl:63
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:64'),  # spec 15.3.5 3dexperience-exchange2.srl:64
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:65'),  # spec 15.3.5 3dexperience-exchange2.srl:65
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:66'),  # spec 15.3.5 3dexperience-exchange2.srl:66
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:67'),  # spec 15.3.5 3dexperience-exchange2.srl:67
        ('put', 'u8', (195,), '15.3.5 3dexperience-exchange2.srl:68'),  # spec 15.3.5 3dexperience-exchange2.srl:68
        ('put', 'u8', (162,), '15.3.5 3dexperience-exchange2.srl:69'),  # spec 15.3.5 3dexperience-exchange2.srl:69
        ('put', 'utf8', ('id',), '15.3.5 3dexperience-exchange2.srl:70'),  # spec 15.3.5 3dexperience-exchange2.srl:70
        ('put', 'u8', (2,), '15.3.5 3dexperience-exchange2.srl:71'),  # spec 15.3.5 3dexperience-exchange2.srl:71
        ('put', 'u8', (164,), '15.3.5 3dexperience-exchange2.srl:72'),  # spec 15.3.5 3dexperience-exchange2.srl:72
        ('put', 'utf8', ('name',), '15.3.5 3dexperience-exchange2.srl:73'),  # spec 15.3.5 3dexperience-exchange2.srl:73
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:74'),  # spec 15.3.5 3dexperience-exchange2.srl:74
        ('put', 'utf8', ('Front Plane',), '15.3.5 3dexperience-exchange2.srl:75'),  # spec 15.3.5 3dexperience-exchange2.srl:75
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:76'),  # spec 15.3.5 3dexperience-exchange2.srl:76
        ('put', 'utf8', ('normal',), '15.3.5 3dexperience-exchange2.srl:77'),  # spec 15.3.5 3dexperience-exchange2.srl:77
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:78'),  # spec 15.3.5 3dexperience-exchange2.srl:78
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:79'),  # spec 15.3.5 3dexperience-exchange2.srl:79
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:80'),  # spec 15.3.5 3dexperience-exchange2.srl:80
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:81'),  # spec 15.3.5 3dexperience-exchange2.srl:81
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:82'),  # spec 15.3.5 3dexperience-exchange2.srl:82
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:83'),  # spec 15.3.5 3dexperience-exchange2.srl:83
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:84'),  # spec 15.3.5 3dexperience-exchange2.srl:84
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:85'),  # spec 15.3.5 3dexperience-exchange2.srl:85
        ('put', 'utf8', ('point',), '15.3.5 3dexperience-exchange2.srl:86'),  # spec 15.3.5 3dexperience-exchange2.srl:86
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:87'),  # spec 15.3.5 3dexperience-exchange2.srl:87
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:88'),  # spec 15.3.5 3dexperience-exchange2.srl:88
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:89'),  # spec 15.3.5 3dexperience-exchange2.srl:89
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:90'),  # spec 15.3.5 3dexperience-exchange2.srl:90
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:91'),  # spec 15.3.5 3dexperience-exchange2.srl:91
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:92'),  # spec 15.3.5 3dexperience-exchange2.srl:92
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:93'),  # spec 15.3.5 3dexperience-exchange2.srl:93
        ('put', 'u8', (167,), '15.3.5 3dexperience-exchange2.srl:94'),  # spec 15.3.5 3dexperience-exchange2.srl:94
        ('put', 'utf8', ('subtype',), '15.3.5 3dexperience-exchange2.srl:95'),  # spec 15.3.5 3dexperience-exchange2.srl:95
        ('put', 'u8', (180,), '15.3.5 3dexperience-exchange2.srl:96'),  # spec 15.3.5 3dexperience-exchange2.srl:96
        ('put', 'utf8', ('swRefPlaneSWStandard',), '15.3.5 3dexperience-exchange2.srl:97'),  # spec 15.3.5 3dexperience-exchange2.srl:97
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:98'),  # spec 15.3.5 3dexperience-exchange2.srl:98
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:99'),  # spec 15.3.5 3dexperience-exchange2.srl:99
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:100'),  # spec 15.3.5 3dexperience-exchange2.srl:100
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:101'),  # spec 15.3.5 3dexperience-exchange2.srl:101
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:102'),  # spec 15.3.5 3dexperience-exchange2.srl:102
        ('put', 'u8', (194,), '15.3.5 3dexperience-exchange2.srl:103'),  # spec 15.3.5 3dexperience-exchange2.srl:103
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:104'),  # spec 15.3.5 3dexperience-exchange2.srl:104
        ('put', 'utf8', ('transform',), '15.3.5 3dexperience-exchange2.srl:105'),  # spec 15.3.5 3dexperience-exchange2.srl:105
        ('put', 'u8', (130,), '15.3.5 3dexperience-exchange2.srl:106'),  # spec 15.3.5 3dexperience-exchange2.srl:106
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:107'),  # spec 15.3.5 3dexperience-exchange2.srl:107
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:108'),  # spec 15.3.5 3dexperience-exchange2.srl:108
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:109'),  # spec 15.3.5 3dexperience-exchange2.srl:109
        ('put', 'utf8', ('mgXform_c',), '15.3.5 3dexperience-exchange2.srl:110'),  # spec 15.3.5 3dexperience-exchange2.srl:110
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:111'),  # spec 15.3.5 3dexperience-exchange2.srl:111
        ('put', 'utf8', ('elems',), '15.3.5 3dexperience-exchange2.srl:112'),  # spec 15.3.5 3dexperience-exchange2.srl:112
        ('put', 'u8', (157,), '15.3.5 3dexperience-exchange2.srl:113'),  # spec 15.3.5 3dexperience-exchange2.srl:113
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:114'),  # spec 15.3.5 3dexperience-exchange2.srl:114
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:115'),  # spec 15.3.5 3dexperience-exchange2.srl:115
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:116'),  # spec 15.3.5 3dexperience-exchange2.srl:116
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:117'),  # spec 15.3.5 3dexperience-exchange2.srl:117
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:118'),  # spec 15.3.5 3dexperience-exchange2.srl:118
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:119'),  # spec 15.3.5 3dexperience-exchange2.srl:119
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:120'),  # spec 15.3.5 3dexperience-exchange2.srl:120
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:121'),  # spec 15.3.5 3dexperience-exchange2.srl:121
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:122'),  # spec 15.3.5 3dexperience-exchange2.srl:122
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:123'),  # spec 15.3.5 3dexperience-exchange2.srl:123
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:124'),  # spec 15.3.5 3dexperience-exchange2.srl:124
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:125'),  # spec 15.3.5 3dexperience-exchange2.srl:125
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:126'),  # spec 15.3.5 3dexperience-exchange2.srl:126
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:127'),  # spec 15.3.5 3dexperience-exchange2.srl:127
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:128'),  # spec 15.3.5 3dexperience-exchange2.srl:128
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:129'),  # spec 15.3.5 3dexperience-exchange2.srl:129
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:130'),  # spec 15.3.5 3dexperience-exchange2.srl:130
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:131'),  # spec 15.3.5 3dexperience-exchange2.srl:131
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:132'),  # spec 15.3.5 3dexperience-exchange2.srl:132
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:133'),  # spec 15.3.5 3dexperience-exchange2.srl:133
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:134'),  # spec 15.3.5 3dexperience-exchange2.srl:134
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:135'),  # spec 15.3.5 3dexperience-exchange2.srl:135
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:136'),  # spec 15.3.5 3dexperience-exchange2.srl:136
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:137'),  # spec 15.3.5 3dexperience-exchange2.srl:137
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:138'),  # spec 15.3.5 3dexperience-exchange2.srl:138
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:139'),  # spec 15.3.5 3dexperience-exchange2.srl:139
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:140'),  # spec 15.3.5 3dexperience-exchange2.srl:140
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:141'),  # spec 15.3.5 3dexperience-exchange2.srl:141
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:142'),  # spec 15.3.5 3dexperience-exchange2.srl:142
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:143'),  # spec 15.3.5 3dexperience-exchange2.srl:143
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:144'),  # spec 15.3.5 3dexperience-exchange2.srl:144
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:145'),  # spec 15.3.5 3dexperience-exchange2.srl:145
        ('put', 'u32be', (('$', 'exch.hash.top'),), '15.3.3 3dexperience-exchange2.srl:32'),  # spec 15.3.3 3dexperience-exchange2.srl:32
        ('put', 'u32be', (36,), '15.3.3 3dexperience-exchange2.srl:33'),  # spec 15.3.3 3dexperience-exchange2.srl:33
        ('put', 'u64be', (395,), '15.3.3 3dexperience-exchange2.srl:34'),  # spec 15.3.3 3dexperience-exchange2.srl:34
        ('put', 'u16be', (12,), '15.3.3 3dexperience-exchange2.srl:35'),  # spec 15.3.3 3dexperience-exchange2.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:36'),  # spec 15.3.3 3dexperience-exchange2.srl:36
        ('put', 'utf8', (('$', 'exch.top'),), '15.3.5 3dexperience-exchange2.srl:150'),  # spec 15.3.5 3dexperience-exchange2.srl:150
        ('put', 'u8', (143,), '15.3.5 3dexperience-exchange2.srl:151'),  # spec 15.3.5 3dexperience-exchange2.srl:151
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:152'),  # spec 15.3.5 3dexperience-exchange2.srl:152
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:153'),  # spec 15.3.5 3dexperience-exchange2.srl:153
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:154'),  # spec 15.3.5 3dexperience-exchange2.srl:154
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:155'),  # spec 15.3.5 3dexperience-exchange2.srl:155
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:156'),  # spec 15.3.5 3dexperience-exchange2.srl:156
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:157'),  # spec 15.3.5 3dexperience-exchange2.srl:157
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:158'),  # spec 15.3.5 3dexperience-exchange2.srl:158
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:159'),  # spec 15.3.5 3dexperience-exchange2.srl:159
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:160'),  # spec 15.3.5 3dexperience-exchange2.srl:160
        ('put', 'utf8', ('description',), '15.3.5 3dexperience-exchange2.srl:161'),  # spec 15.3.5 3dexperience-exchange2.srl:161
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:162'),  # spec 15.3.5 3dexperience-exchange2.srl:162
        ('put', 'utf8', ('Top Plane',), '15.3.5 3dexperience-exchange2.srl:163'),  # spec 15.3.5 3dexperience-exchange2.srl:163
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:164'),  # spec 15.3.5 3dexperience-exchange2.srl:164
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:165'),  # spec 15.3.5 3dexperience-exchange2.srl:165
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:166'),  # spec 15.3.5 3dexperience-exchange2.srl:166
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:167'),  # spec 15.3.5 3dexperience-exchange2.srl:167
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:168'),  # spec 15.3.5 3dexperience-exchange2.srl:168
        ('put', 'u8', (195,), '15.3.5 3dexperience-exchange2.srl:169'),  # spec 15.3.5 3dexperience-exchange2.srl:169
        ('put', 'u8', (162,), '15.3.5 3dexperience-exchange2.srl:170'),  # spec 15.3.5 3dexperience-exchange2.srl:170
        ('put', 'utf8', ('id',), '15.3.5 3dexperience-exchange2.srl:171'),  # spec 15.3.5 3dexperience-exchange2.srl:171
        ('put', 'u8', (3,), '15.3.5 3dexperience-exchange2.srl:172'),  # spec 15.3.5 3dexperience-exchange2.srl:172
        ('put', 'u8', (164,), '15.3.5 3dexperience-exchange2.srl:173'),  # spec 15.3.5 3dexperience-exchange2.srl:173
        ('put', 'utf8', ('name',), '15.3.5 3dexperience-exchange2.srl:174'),  # spec 15.3.5 3dexperience-exchange2.srl:174
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:175'),  # spec 15.3.5 3dexperience-exchange2.srl:175
        ('put', 'utf8', ('Top Plane',), '15.3.5 3dexperience-exchange2.srl:176'),  # spec 15.3.5 3dexperience-exchange2.srl:176
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:177'),  # spec 15.3.5 3dexperience-exchange2.srl:177
        ('put', 'utf8', ('normal',), '15.3.5 3dexperience-exchange2.srl:178'),  # spec 15.3.5 3dexperience-exchange2.srl:178
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:179'),  # spec 15.3.5 3dexperience-exchange2.srl:179
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:180'),  # spec 15.3.5 3dexperience-exchange2.srl:180
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:181'),  # spec 15.3.5 3dexperience-exchange2.srl:181
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:182'),  # spec 15.3.5 3dexperience-exchange2.srl:182
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:183'),  # spec 15.3.5 3dexperience-exchange2.srl:183
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:184'),  # spec 15.3.5 3dexperience-exchange2.srl:184
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:185'),  # spec 15.3.5 3dexperience-exchange2.srl:185
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:186'),  # spec 15.3.5 3dexperience-exchange2.srl:186
        ('put', 'utf8', ('point',), '15.3.5 3dexperience-exchange2.srl:187'),  # spec 15.3.5 3dexperience-exchange2.srl:187
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:188'),  # spec 15.3.5 3dexperience-exchange2.srl:188
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:189'),  # spec 15.3.5 3dexperience-exchange2.srl:189
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:190'),  # spec 15.3.5 3dexperience-exchange2.srl:190
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:191'),  # spec 15.3.5 3dexperience-exchange2.srl:191
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:192'),  # spec 15.3.5 3dexperience-exchange2.srl:192
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:193'),  # spec 15.3.5 3dexperience-exchange2.srl:193
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:194'),  # spec 15.3.5 3dexperience-exchange2.srl:194
        ('put', 'u8', (167,), '15.3.5 3dexperience-exchange2.srl:195'),  # spec 15.3.5 3dexperience-exchange2.srl:195
        ('put', 'utf8', ('subtype',), '15.3.5 3dexperience-exchange2.srl:196'),  # spec 15.3.5 3dexperience-exchange2.srl:196
        ('put', 'u8', (180,), '15.3.5 3dexperience-exchange2.srl:197'),  # spec 15.3.5 3dexperience-exchange2.srl:197
        ('put', 'utf8', ('swRefPlaneSWStandard',), '15.3.5 3dexperience-exchange2.srl:198'),  # spec 15.3.5 3dexperience-exchange2.srl:198
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:199'),  # spec 15.3.5 3dexperience-exchange2.srl:199
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:200'),  # spec 15.3.5 3dexperience-exchange2.srl:200
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:201'),  # spec 15.3.5 3dexperience-exchange2.srl:201
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:202'),  # spec 15.3.5 3dexperience-exchange2.srl:202
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:203'),  # spec 15.3.5 3dexperience-exchange2.srl:203
        ('put', 'u8', (194,), '15.3.5 3dexperience-exchange2.srl:204'),  # spec 15.3.5 3dexperience-exchange2.srl:204
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:205'),  # spec 15.3.5 3dexperience-exchange2.srl:205
        ('put', 'utf8', ('transform',), '15.3.5 3dexperience-exchange2.srl:206'),  # spec 15.3.5 3dexperience-exchange2.srl:206
        ('put', 'u8', (130,), '15.3.5 3dexperience-exchange2.srl:207'),  # spec 15.3.5 3dexperience-exchange2.srl:207
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:208'),  # spec 15.3.5 3dexperience-exchange2.srl:208
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:209'),  # spec 15.3.5 3dexperience-exchange2.srl:209
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:210'),  # spec 15.3.5 3dexperience-exchange2.srl:210
        ('put', 'utf8', ('mgXform_c',), '15.3.5 3dexperience-exchange2.srl:211'),  # spec 15.3.5 3dexperience-exchange2.srl:211
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:212'),  # spec 15.3.5 3dexperience-exchange2.srl:212
        ('put', 'utf8', ('elems',), '15.3.5 3dexperience-exchange2.srl:213'),  # spec 15.3.5 3dexperience-exchange2.srl:213
        ('put', 'u8', (157,), '15.3.5 3dexperience-exchange2.srl:214'),  # spec 15.3.5 3dexperience-exchange2.srl:214
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:215'),  # spec 15.3.5 3dexperience-exchange2.srl:215
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:216'),  # spec 15.3.5 3dexperience-exchange2.srl:216
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:217'),  # spec 15.3.5 3dexperience-exchange2.srl:217
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:218'),  # spec 15.3.5 3dexperience-exchange2.srl:218
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:219'),  # spec 15.3.5 3dexperience-exchange2.srl:219
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:220'),  # spec 15.3.5 3dexperience-exchange2.srl:220
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:221'),  # spec 15.3.5 3dexperience-exchange2.srl:221
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:222'),  # spec 15.3.5 3dexperience-exchange2.srl:222
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:223'),  # spec 15.3.5 3dexperience-exchange2.srl:223
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:224'),  # spec 15.3.5 3dexperience-exchange2.srl:224
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:225'),  # spec 15.3.5 3dexperience-exchange2.srl:225
        ('put', 'f64be', (-1.0,), '15.3.5 3dexperience-exchange2.srl:226'),  # spec 15.3.5 3dexperience-exchange2.srl:226
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:227'),  # spec 15.3.5 3dexperience-exchange2.srl:227
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:228'),  # spec 15.3.5 3dexperience-exchange2.srl:228
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:229'),  # spec 15.3.5 3dexperience-exchange2.srl:229
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:230'),  # spec 15.3.5 3dexperience-exchange2.srl:230
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:231'),  # spec 15.3.5 3dexperience-exchange2.srl:231
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:232'),  # spec 15.3.5 3dexperience-exchange2.srl:232
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:233'),  # spec 15.3.5 3dexperience-exchange2.srl:233
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:234'),  # spec 15.3.5 3dexperience-exchange2.srl:234
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:235'),  # spec 15.3.5 3dexperience-exchange2.srl:235
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:236'),  # spec 15.3.5 3dexperience-exchange2.srl:236
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:237'),  # spec 15.3.5 3dexperience-exchange2.srl:237
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:238'),  # spec 15.3.5 3dexperience-exchange2.srl:238
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:239'),  # spec 15.3.5 3dexperience-exchange2.srl:239
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:240'),  # spec 15.3.5 3dexperience-exchange2.srl:240
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:241'),  # spec 15.3.5 3dexperience-exchange2.srl:241
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:242'),  # spec 15.3.5 3dexperience-exchange2.srl:242
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:243'),  # spec 15.3.5 3dexperience-exchange2.srl:243
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:244'),  # spec 15.3.5 3dexperience-exchange2.srl:244
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:245'),  # spec 15.3.5 3dexperience-exchange2.srl:245
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:246'),  # spec 15.3.5 3dexperience-exchange2.srl:246
        ('put', 'u32be', (('$', 'exch.hash.right'),), '15.3.3 3dexperience-exchange2.srl:32'),  # spec 15.3.3 3dexperience-exchange2.srl:32
        ('put', 'u32be', (36,), '15.3.3 3dexperience-exchange2.srl:33'),  # spec 15.3.3 3dexperience-exchange2.srl:33
        ('put', 'u64be', (399,), '15.3.3 3dexperience-exchange2.srl:34'),  # spec 15.3.3 3dexperience-exchange2.srl:34
        ('put', 'u16be', (473,), '15.3.3 3dexperience-exchange2.srl:35'),  # spec 15.3.3 3dexperience-exchange2.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:36'),  # spec 15.3.3 3dexperience-exchange2.srl:36
        ('put', 'utf8', (('$', 'exch.right'),), '15.3.5 3dexperience-exchange2.srl:251'),  # spec 15.3.5 3dexperience-exchange2.srl:251
        ('put', 'u8', (143,), '15.3.5 3dexperience-exchange2.srl:252'),  # spec 15.3.5 3dexperience-exchange2.srl:252
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:253'),  # spec 15.3.5 3dexperience-exchange2.srl:253
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:254'),  # spec 15.3.5 3dexperience-exchange2.srl:254
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:255'),  # spec 15.3.5 3dexperience-exchange2.srl:255
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:256'),  # spec 15.3.5 3dexperience-exchange2.srl:256
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:257'),  # spec 15.3.5 3dexperience-exchange2.srl:257
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:258'),  # spec 15.3.5 3dexperience-exchange2.srl:258
        ('put', 'u8', (172,), '15.3.5 3dexperience-exchange2.srl:259'),  # spec 15.3.5 3dexperience-exchange2.srl:259
        ('put', 'utf8', ('moRefPlane_c',), '15.3.5 3dexperience-exchange2.srl:260'),  # spec 15.3.5 3dexperience-exchange2.srl:260
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:261'),  # spec 15.3.5 3dexperience-exchange2.srl:261
        ('put', 'utf8', ('description',), '15.3.5 3dexperience-exchange2.srl:262'),  # spec 15.3.5 3dexperience-exchange2.srl:262
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:263'),  # spec 15.3.5 3dexperience-exchange2.srl:263
        ('put', 'utf8', ('Right Plane',), '15.3.5 3dexperience-exchange2.srl:264'),  # spec 15.3.5 3dexperience-exchange2.srl:264
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:265'),  # spec 15.3.5 3dexperience-exchange2.srl:265
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:266'),  # spec 15.3.5 3dexperience-exchange2.srl:266
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:267'),  # spec 15.3.5 3dexperience-exchange2.srl:267
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:268'),  # spec 15.3.5 3dexperience-exchange2.srl:268
        ('put', 'utf8', ('hidden',), '15.3.5 3dexperience-exchange2.srl:269'),  # spec 15.3.5 3dexperience-exchange2.srl:269
        ('put', 'u8', (195,), '15.3.5 3dexperience-exchange2.srl:270'),  # spec 15.3.5 3dexperience-exchange2.srl:270
        ('put', 'u8', (162,), '15.3.5 3dexperience-exchange2.srl:271'),  # spec 15.3.5 3dexperience-exchange2.srl:271
        ('put', 'utf8', ('id',), '15.3.5 3dexperience-exchange2.srl:272'),  # spec 15.3.5 3dexperience-exchange2.srl:272
        ('put', 'u8', (4,), '15.3.5 3dexperience-exchange2.srl:273'),  # spec 15.3.5 3dexperience-exchange2.srl:273
        ('put', 'u8', (164,), '15.3.5 3dexperience-exchange2.srl:274'),  # spec 15.3.5 3dexperience-exchange2.srl:274
        ('put', 'utf8', ('name',), '15.3.5 3dexperience-exchange2.srl:275'),  # spec 15.3.5 3dexperience-exchange2.srl:275
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:276'),  # spec 15.3.5 3dexperience-exchange2.srl:276
        ('put', 'utf8', ('Right Plane',), '15.3.5 3dexperience-exchange2.srl:277'),  # spec 15.3.5 3dexperience-exchange2.srl:277
        ('put', 'u8', (166,), '15.3.5 3dexperience-exchange2.srl:278'),  # spec 15.3.5 3dexperience-exchange2.srl:278
        ('put', 'utf8', ('normal',), '15.3.5 3dexperience-exchange2.srl:279'),  # spec 15.3.5 3dexperience-exchange2.srl:279
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:280'),  # spec 15.3.5 3dexperience-exchange2.srl:280
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:281'),  # spec 15.3.5 3dexperience-exchange2.srl:281
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:282'),  # spec 15.3.5 3dexperience-exchange2.srl:282
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:283'),  # spec 15.3.5 3dexperience-exchange2.srl:283
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:284'),  # spec 15.3.5 3dexperience-exchange2.srl:284
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:285'),  # spec 15.3.5 3dexperience-exchange2.srl:285
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:286'),  # spec 15.3.5 3dexperience-exchange2.srl:286
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:287'),  # spec 15.3.5 3dexperience-exchange2.srl:287
        ('put', 'utf8', ('point',), '15.3.5 3dexperience-exchange2.srl:288'),  # spec 15.3.5 3dexperience-exchange2.srl:288
        ('put', 'u8', (147,), '15.3.5 3dexperience-exchange2.srl:289'),  # spec 15.3.5 3dexperience-exchange2.srl:289
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:290'),  # spec 15.3.5 3dexperience-exchange2.srl:290
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:291'),  # spec 15.3.5 3dexperience-exchange2.srl:291
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:292'),  # spec 15.3.5 3dexperience-exchange2.srl:292
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:293'),  # spec 15.3.5 3dexperience-exchange2.srl:293
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:294'),  # spec 15.3.5 3dexperience-exchange2.srl:294
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:295'),  # spec 15.3.5 3dexperience-exchange2.srl:295
        ('put', 'u8', (167,), '15.3.5 3dexperience-exchange2.srl:296'),  # spec 15.3.5 3dexperience-exchange2.srl:296
        ('put', 'utf8', ('subtype',), '15.3.5 3dexperience-exchange2.srl:297'),  # spec 15.3.5 3dexperience-exchange2.srl:297
        ('put', 'u8', (180,), '15.3.5 3dexperience-exchange2.srl:298'),  # spec 15.3.5 3dexperience-exchange2.srl:298
        ('put', 'utf8', ('swRefPlaneSWStandard',), '15.3.5 3dexperience-exchange2.srl:299'),  # spec 15.3.5 3dexperience-exchange2.srl:299
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:300'),  # spec 15.3.5 3dexperience-exchange2.srl:300
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:301'),  # spec 15.3.5 3dexperience-exchange2.srl:301
        ('put', 'u8', (0,), '15.3.5 3dexperience-exchange2.srl:302'),  # spec 15.3.5 3dexperience-exchange2.srl:302
        ('put', 'u8', (170,), '15.3.5 3dexperience-exchange2.srl:303'),  # spec 15.3.5 3dexperience-exchange2.srl:303
        ('put', 'utf8', ('suppressed',), '15.3.5 3dexperience-exchange2.srl:304'),  # spec 15.3.5 3dexperience-exchange2.srl:304
        ('put', 'u8', (194,), '15.3.5 3dexperience-exchange2.srl:305'),  # spec 15.3.5 3dexperience-exchange2.srl:305
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:306'),  # spec 15.3.5 3dexperience-exchange2.srl:306
        ('put', 'utf8', ('transform',), '15.3.5 3dexperience-exchange2.srl:307'),  # spec 15.3.5 3dexperience-exchange2.srl:307
        ('put', 'u8', (130,), '15.3.5 3dexperience-exchange2.srl:308'),  # spec 15.3.5 3dexperience-exchange2.srl:308
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:309'),  # spec 15.3.5 3dexperience-exchange2.srl:309
        ('put', 'utf8', ('class',), '15.3.5 3dexperience-exchange2.srl:310'),  # spec 15.3.5 3dexperience-exchange2.srl:310
        ('put', 'u8', (169,), '15.3.5 3dexperience-exchange2.srl:311'),  # spec 15.3.5 3dexperience-exchange2.srl:311
        ('put', 'utf8', ('mgXform_c',), '15.3.5 3dexperience-exchange2.srl:312'),  # spec 15.3.5 3dexperience-exchange2.srl:312
        ('put', 'u8', (165,), '15.3.5 3dexperience-exchange2.srl:313'),  # spec 15.3.5 3dexperience-exchange2.srl:313
        ('put', 'utf8', ('elems',), '15.3.5 3dexperience-exchange2.srl:314'),  # spec 15.3.5 3dexperience-exchange2.srl:314
        ('put', 'u8', (157,), '15.3.5 3dexperience-exchange2.srl:315'),  # spec 15.3.5 3dexperience-exchange2.srl:315
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:316'),  # spec 15.3.5 3dexperience-exchange2.srl:316
        ('put', 'f64be', (-0.0,), '15.3.5 3dexperience-exchange2.srl:317'),  # spec 15.3.5 3dexperience-exchange2.srl:317
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:318'),  # spec 15.3.5 3dexperience-exchange2.srl:318
        ('put', 'f64be', (-0.0,), '15.3.5 3dexperience-exchange2.srl:319'),  # spec 15.3.5 3dexperience-exchange2.srl:319
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:320'),  # spec 15.3.5 3dexperience-exchange2.srl:320
        ('put', 'f64be', (-1.0,), '15.3.5 3dexperience-exchange2.srl:321'),  # spec 15.3.5 3dexperience-exchange2.srl:321
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:322'),  # spec 15.3.5 3dexperience-exchange2.srl:322
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:323'),  # spec 15.3.5 3dexperience-exchange2.srl:323
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:324'),  # spec 15.3.5 3dexperience-exchange2.srl:324
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:325'),  # spec 15.3.5 3dexperience-exchange2.srl:325
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:326'),  # spec 15.3.5 3dexperience-exchange2.srl:326
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:327'),  # spec 15.3.5 3dexperience-exchange2.srl:327
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:328'),  # spec 15.3.5 3dexperience-exchange2.srl:328
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:329'),  # spec 15.3.5 3dexperience-exchange2.srl:329
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:330'),  # spec 15.3.5 3dexperience-exchange2.srl:330
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:331'),  # spec 15.3.5 3dexperience-exchange2.srl:331
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:332'),  # spec 15.3.5 3dexperience-exchange2.srl:332
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:333'),  # spec 15.3.5 3dexperience-exchange2.srl:333
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:334'),  # spec 15.3.5 3dexperience-exchange2.srl:334
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:335'),  # spec 15.3.5 3dexperience-exchange2.srl:335
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:336'),  # spec 15.3.5 3dexperience-exchange2.srl:336
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:337'),  # spec 15.3.5 3dexperience-exchange2.srl:337
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:338'),  # spec 15.3.5 3dexperience-exchange2.srl:338
        ('put', 'f64be', (0.0,), '15.3.5 3dexperience-exchange2.srl:339'),  # spec 15.3.5 3dexperience-exchange2.srl:339
        ('put', 'u8', (203,), '15.3.5 3dexperience-exchange2.srl:340'),  # spec 15.3.5 3dexperience-exchange2.srl:340
        ('put', 'f64be', (1.0,), '15.3.5 3dexperience-exchange2.srl:341'),  # spec 15.3.5 3dexperience-exchange2.srl:341
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:342'),  # spec 15.3.5 3dexperience-exchange2.srl:342
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:343'),  # spec 15.3.5 3dexperience-exchange2.srl:343
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:344'),  # spec 15.3.5 3dexperience-exchange2.srl:344
        ('put', 'u8', (171,), '15.3.5 3dexperience-exchange2.srl:345'),  # spec 15.3.5 3dexperience-exchange2.srl:345
        ('put', 'utf8', ('updatestamp',), '15.3.5 3dexperience-exchange2.srl:346'),  # spec 15.3.5 3dexperience-exchange2.srl:346
        ('put', 'u8', (101,), '15.3.5 3dexperience-exchange2.srl:347'),  # spec 15.3.5 3dexperience-exchange2.srl:347
        ('put', 'u32be', (193471147,), '15.3.3 3dexperience-exchange2.srl:32'),  # spec 15.3.3 3dexperience-exchange2.srl:32
        ('put', 'u32be', (3,), '15.3.3 3dexperience-exchange2.srl:33'),  # spec 15.3.3 3dexperience-exchange2.srl:33
        ('put', 'u64be', (288,), '15.3.3 3dexperience-exchange2.srl:34'),  # spec 15.3.3 3dexperience-exchange2.srl:34
        ('put', 'u16be', (930,), '15.3.3 3dexperience-exchange2.srl:35'),  # spec 15.3.3 3dexperience-exchange2.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:36'),  # spec 15.3.3 3dexperience-exchange2.srl:36
        ('put', 'latin1', ('TOC',), '15.3.6 3dexperience-exchange2.srl:352'),  # spec 15.3.6 3dexperience-exchange2.srl:352
        ('put', 'u8', (130,), '15.3.6 3dexperience-exchange2.srl:353'),  # spec 15.3.6 3dexperience-exchange2.srl:353
        ('put', 'u8', (165,), '15.3.6 3dexperience-exchange2.srl:354'),  # spec 15.3.6 3dexperience-exchange2.srl:354
        ('put', 'utf8', ('class',), '15.3.6 3dexperience-exchange2.srl:355'),  # spec 15.3.6 3dexperience-exchange2.srl:355
        ('put', 'u8', (170,), '15.3.6 3dexperience-exchange2.srl:356'),  # spec 15.3.6 3dexperience-exchange2.srl:356
        ('put', 'utf8', ('object-map',), '15.3.6 3dexperience-exchange2.srl:357'),  # spec 15.3.6 3dexperience-exchange2.srl:357
        ('put', 'u8', (165,), '15.3.6 3dexperience-exchange2.srl:358'),  # spec 15.3.6 3dexperience-exchange2.srl:358
        ('put', 'utf8', ('model',), '15.3.6 3dexperience-exchange2.srl:359'),  # spec 15.3.6 3dexperience-exchange2.srl:359
        ('put', 'u8', (132,), '15.3.6 3dexperience-exchange2.srl:360'),  # spec 15.3.6 3dexperience-exchange2.srl:360
        ('put', 'u8', (165,), '15.3.6 3dexperience-exchange2.srl:361'),  # spec 15.3.6 3dexperience-exchange2.srl:361
        ('put', 'utf8', ('class',), '15.3.6 3dexperience-exchange2.srl:362'),  # spec 15.3.6 3dexperience-exchange2.srl:362
        ('put', 'u8', (168,), '15.3.6 3dexperience-exchange2.srl:363'),  # spec 15.3.6 3dexperience-exchange2.srl:363
        ('put', 'utf8', ('moPart_c',), '15.3.6 3dexperience-exchange2.srl:364'),  # spec 15.3.6 3dexperience-exchange2.srl:364
        ('put', 'u8', (168,), '15.3.6 3dexperience-exchange2.srl:365'),  # spec 15.3.6 3dexperience-exchange2.srl:365
        ('put', 'utf8', ('configid',), '15.3.6 3dexperience-exchange2.srl:366'),  # spec 15.3.6 3dexperience-exchange2.srl:366
        ('put', 'u8', (0,), '15.3.6 3dexperience-exchange2.srl:367'),  # spec 15.3.6 3dexperience-exchange2.srl:367
        ('put', 'u8', (170,), '15.3.6 3dexperience-exchange2.srl:368'),  # spec 15.3.6 3dexperience-exchange2.srl:368
        ('put', 'utf8', ('configname',), '15.3.6 3dexperience-exchange2.srl:369'),  # spec 15.3.6 3dexperience-exchange2.srl:369
        ('put', 'u8', (167,), '15.3.6 3dexperience-exchange2.srl:370'),  # spec 15.3.6 3dexperience-exchange2.srl:370
        ('put', 'utf8', ('Default',), '15.3.6 3dexperience-exchange2.srl:371'),  # spec 15.3.6 3dexperience-exchange2.srl:371
        ('put', 'u8', (166,), '15.3.6 3dexperience-exchange2.srl:372'),  # spec 15.3.6 3dexperience-exchange2.srl:372
        ('put', 'utf8', ('object',), '15.3.6 3dexperience-exchange2.srl:373'),  # spec 15.3.6 3dexperience-exchange2.srl:373
        ('put', 'u8', (132,), '15.3.6 3dexperience-exchange2.srl:374'),  # spec 15.3.6 3dexperience-exchange2.srl:374
        ('put', 'u8', (165,), '15.3.6 3dexperience-exchange2.srl:375'),  # spec 15.3.6 3dexperience-exchange2.srl:375
        ('put', 'utf8', ('class',), '15.3.6 3dexperience-exchange2.srl:376'),  # spec 15.3.6 3dexperience-exchange2.srl:376
        ('put', 'u8', (172,), '15.3.6 3dexperience-exchange2.srl:377'),  # spec 15.3.6 3dexperience-exchange2.srl:377
        ('put', 'utf8', ('moRefPlane_c',), '15.3.6 3dexperience-exchange2.srl:378'),  # spec 15.3.6 3dexperience-exchange2.srl:378
        ('for', 'g', ('$', 'exch.toc'), False, (  # spec 15.3.6 3dexperience-exchange2.srl:380
            ('put', 'u8', (166,), '15.3.6 3dexperience-exchange2.srl:381'),  # spec 15.3.6 3dexperience-exchange2.srl:381
            ('put', 'utf8', ('object',), '15.3.6 3dexperience-exchange2.srl:382'),  # spec 15.3.6 3dexperience-exchange2.srl:382
            ('put', 'u8', (130,), '15.3.6 3dexperience-exchange2.srl:383'),  # spec 15.3.6 3dexperience-exchange2.srl:383
            ('put', 'u8', (165,), '15.3.6 3dexperience-exchange2.srl:384'),  # spec 15.3.6 3dexperience-exchange2.srl:384
            ('put', 'utf8', ('class',), '15.3.6 3dexperience-exchange2.srl:385'),  # spec 15.3.6 3dexperience-exchange2.srl:385
            ('put', 'u8', (166,), '15.3.6 3dexperience-exchange2.srl:386'),  # spec 15.3.6 3dexperience-exchange2.srl:386
            ('put', 'utf8', ('object',), '15.3.6 3dexperience-exchange2.srl:387'),  # spec 15.3.6 3dexperience-exchange2.srl:387
            ('put', 'u8', (164,), '15.3.6 3dexperience-exchange2.srl:388'),  # spec 15.3.6 3dexperience-exchange2.srl:388
            ('put', 'utf8', ('guid',), '15.3.6 3dexperience-exchange2.srl:389'),  # spec 15.3.6 3dexperience-exchange2.srl:389
            ('put', 'u8', (217,), '15.3.6 3dexperience-exchange2.srl:390'),  # spec 15.3.6 3dexperience-exchange2.srl:390
            ('put', 'u8', (36,), '15.3.6 3dexperience-exchange2.srl:391'),  # spec 15.3.6 3dexperience-exchange2.srl:391
            ('put', 'utf8', (('$', 'g'),), '15.3.6 3dexperience-exchange2.srl:392'),  # spec 15.3.6 3dexperience-exchange2.srl:392
        ), '15.3.6 3dexperience-exchange2.srl:380'),  # spec 15.3.6 3dexperience-exchange2.srl:380
        ('put', 'u32be', (('$', 'exch.hash.doc'),), '15.3.3 3dexperience-exchange2.srl:32'),  # spec 15.3.3 3dexperience-exchange2.srl:32
        ('put', 'u32be', (36,), '15.3.3 3dexperience-exchange2.srl:33'),  # spec 15.3.3 3dexperience-exchange2.srl:33
        ('put', 'u64be', (122,), '15.3.3 3dexperience-exchange2.srl:34'),  # spec 15.3.3 3dexperience-exchange2.srl:34
        ('put', 'u16be', (1391,), '15.3.3 3dexperience-exchange2.srl:35'),  # spec 15.3.3 3dexperience-exchange2.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-exchange2.srl:36'),  # spec 15.3.3 3dexperience-exchange2.srl:36
        ('put', 'utf8', (('$', 'exch.doc'),), '15.3.7 3dexperience-exchange2.srl:398'),  # spec 15.3.7 3dexperience-exchange2.srl:398
        ('put', 'u8', (133,), '15.3.7 3dexperience-exchange2.srl:399'),  # spec 15.3.7 3dexperience-exchange2.srl:399
        ('put', 'u8', (175,), '15.3.7 3dexperience-exchange2.srl:400'),  # spec 15.3.7 3dexperience-exchange2.srl:400
        ('put', 'utf8', ('SaveAsNewCalled',), '15.3.7 3dexperience-exchange2.srl:401'),  # spec 15.3.7 3dexperience-exchange2.srl:401
        ('put', 'u8', (194,), '15.3.7 3dexperience-exchange2.srl:402'),  # spec 15.3.7 3dexperience-exchange2.srl:402
        ('put', 'u8', (165,), '15.3.7 3dexperience-exchange2.srl:403'),  # spec 15.3.7 3dexperience-exchange2.srl:403
        ('put', 'utf8', ('class',), '15.3.7 3dexperience-exchange2.srl:404'),  # spec 15.3.7 3dexperience-exchange2.srl:404
        ('put', 'u8', (171,), '15.3.7 3dexperience-exchange2.srl:405'),  # spec 15.3.7 3dexperience-exchange2.srl:405
        ('put', 'utf8', ('uiPartDoc_c',), '15.3.7 3dexperience-exchange2.srl:406'),  # spec 15.3.7 3dexperience-exchange2.srl:406
        ('put', 'u8', (172,), '15.3.7 3dexperience-exchange2.srl:407'),  # spec 15.3.7 3dexperience-exchange2.srl:407
        ('put', 'utf8', ('platformflag',), '15.3.7 3dexperience-exchange2.srl:408'),  # spec 15.3.7 3dexperience-exchange2.srl:408
        ('put', 'u8', (2,), '15.3.7 3dexperience-exchange2.srl:409'),  # spec 15.3.7 3dexperience-exchange2.srl:409
        ('put', 'u8', (188,), '15.3.7 3dexperience-exchange2.srl:410'),  # spec 15.3.7 3dexperience-exchange2.srl:410
        ('put', 'utf8', ('repairDTForDefaultConfigflag',), '15.3.7 3dexperience-exchange2.srl:411'),  # spec 15.3.7 3dexperience-exchange2.srl:411
        ('put', 'u8', (194,), '15.3.7 3dexperience-exchange2.srl:412'),  # spec 15.3.7 3dexperience-exchange2.srl:412
        ('put', 'u8', (217,), '15.3.7 3dexperience-exchange2.srl:413'),  # spec 15.3.7 3dexperience-exchange2.srl:413
        ('put', 'u8', (39,), '15.3.7 3dexperience-exchange2.srl:414'),  # spec 15.3.7 3dexperience-exchange2.srl:414
        ('put', 'utf8', ('useEnglishDescriptionForWeldmentCutList',), '15.3.7 3dexperience-exchange2.srl:415'),  # spec 15.3.7 3dexperience-exchange2.srl:415
        ('put', 'u8', (194,), '15.3.7 3dexperience-exchange2.srl:416'),  # spec 15.3.7 3dexperience-exchange2.srl:416
        ('put', 'u16be', (0,), '15.3.4 3dexperience-exchange2.srl:420'),  # spec 15.3.4 3dexperience-exchange2.srl:420
        ('put', 'u16be', (2204,), '15.3.4 3dexperience-exchange2.srl:421'),  # spec 15.3.4 3dexperience-exchange2.srl:421
        ('rep', 2200, 0, '15.3.4 3dexperience-exchange2.srl:422'),  # spec 15.3.4 3dexperience-exchange2.srl:422
    ),  # spec 15.3 3dexperience-exchange2.srl
    'Contents/3DExperienceExchange_ConfigHeader': (  # spec 15.3 3dexperience-configheader.srl
        ('put', 'latin1', ('unqlite',), '15.3.2 3dexperience-configheader.srl:6'),  # spec 15.3.2 3dexperience-configheader.srl:6
        ('put', 'u32be', (3682346770,), '15.3.2 3dexperience-configheader.srl:7'),  # spec 15.3.2 3dexperience-configheader.srl:7
        ('put', 'u16be', (('=', '($exch.time.year-1980)*512+($exch.time.month-1)*32+$exch.time.day'),), '15.3.2 3dexperience-configheader.srl:9'),  # spec 15.3.2 3dexperience-configheader.srl:9
        ('put', 'u16be', (('=', '$exch.time.hour*2048+$exch.time.minute*32+$exch.time.second//2'),), '15.3.2 3dexperience-configheader.srl:10'),  # spec 15.3.2 3dexperience-configheader.srl:10
        ('put', 'u32be', (512,), '15.3.2 3dexperience-configheader.srl:11'),  # spec 15.3.2 3dexperience-configheader.srl:11
        ('put', 'u32be', (4096,), '15.3.2 3dexperience-configheader.srl:12'),  # spec 15.3.2 3dexperience-configheader.srl:12
        ('put', 'u16be', (4,), '15.3.2 3dexperience-configheader.srl:13'),  # spec 15.3.2 3dexperience-configheader.srl:13
        ('put', 'latin1', ('hash',), '15.3.2 3dexperience-configheader.srl:14'),  # spec 15.3.2 3dexperience-configheader.srl:14
        ('rep', 4067, 0, '15.3.2 3dexperience-configheader.srl:15'),  # spec 15.3.2 3dexperience-configheader.srl:15
        ('put', 'u32be', (4202180043,), '15.3.3 3dexperience-configheader.srl:19'),  # spec 15.3.3 3dexperience-configheader.srl:19
        ('put', 'u32be', (66397173,), '15.3.3 3dexperience-configheader.srl:20'),  # spec 15.3.3 3dexperience-configheader.srl:20
        ('put', 'u64be', (0,), '15.3.3 3dexperience-configheader.srl:21'),  # spec 15.3.3 3dexperience-configheader.srl:21
        ('put', 'u64be', (0,), '15.3.3 3dexperience-configheader.srl:22'),  # spec 15.3.3 3dexperience-configheader.srl:22
        ('put', 'u64be', (1,), '15.3.3 3dexperience-configheader.srl:23'),  # spec 15.3.3 3dexperience-configheader.srl:23
        ('put', 'u64be', (0,), '15.3.3 3dexperience-configheader.srl:24'),  # spec 15.3.3 3dexperience-configheader.srl:24
        ('put', 'u32be', (1,), '15.3.3 3dexperience-configheader.srl:25'),  # spec 15.3.3 3dexperience-configheader.srl:25
        ('put', 'u64be', (0,), '15.3.3 3dexperience-configheader.srl:26'),  # spec 15.3.3 3dexperience-configheader.srl:26
        ('put', 'u64be', (2,), '15.3.3 3dexperience-configheader.srl:27'),  # spec 15.3.3 3dexperience-configheader.srl:27
        ('rep', 4036, 0, '15.3.3 3dexperience-configheader.srl:28'),  # spec 15.3.3 3dexperience-configheader.srl:28
        ('put', 'u16be', (12,), '15.3.4 3dexperience-configheader.srl:41'),  # spec 15.3.4 3dexperience-configheader.srl:41
        ('put', 'u16be', (143,), '15.3.4 3dexperience-configheader.srl:42'),  # spec 15.3.4 3dexperience-configheader.srl:42
        ('put', 'u64be', (0,), '15.3.4 3dexperience-configheader.srl:43'),  # spec 15.3.4 3dexperience-configheader.srl:43
        ('put', 'u32be', (('$', 'exch.hash.config'),), '15.3.3 3dexperience-configheader.srl:32'),  # spec 15.3.3 3dexperience-configheader.srl:32
        ('put', 'u32be', (36,), '15.3.3 3dexperience-configheader.srl:33'),  # spec 15.3.3 3dexperience-configheader.srl:33
        ('put', 'u64be', (69,), '15.3.3 3dexperience-configheader.srl:34'),  # spec 15.3.3 3dexperience-configheader.srl:34
        ('put', 'u16be', (0,), '15.3.3 3dexperience-configheader.srl:35'),  # spec 15.3.3 3dexperience-configheader.srl:35
        ('put', 'u64be', (0,), '15.3.3 3dexperience-configheader.srl:36'),  # spec 15.3.3 3dexperience-configheader.srl:36
        ('put', 'utf8', (('$', 'exch.config'),), '15.3.8 3dexperience-configheader.srl:48'),  # spec 15.3.8 3dexperience-configheader.srl:48
        ('put', 'u8', (132,), '15.3.8 3dexperience-configheader.srl:49'),  # spec 15.3.8 3dexperience-configheader.srl:49
        ('put', 'u8', (165,), '15.3.8 3dexperience-configheader.srl:50'),  # spec 15.3.8 3dexperience-configheader.srl:50
        ('put', 'utf8', ('class',), '15.3.8 3dexperience-configheader.srl:51'),  # spec 15.3.8 3dexperience-configheader.srl:51
        ('put', 'u8', (176,), '15.3.8 3dexperience-configheader.srl:52'),  # spec 15.3.8 3dexperience-configheader.srl:52
        ('put', 'utf8', ('dmConfigHeader_c',), '15.3.8 3dexperience-configheader.srl:53'),  # spec 15.3.8 3dexperience-configheader.srl:53
        ('put', 'u8', (186,), '15.3.8 3dexperience-configheader.srl:54'),  # spec 15.3.8 3dexperience-configheader.srl:54
        ('put', 'utf8', ('configHeaderfamilyMemberID',), '15.3.8 3dexperience-configheader.srl:55'),  # spec 15.3.8 3dexperience-configheader.srl:55
        ('put', 'u8', (254,), '15.3.8 3dexperience-configheader.srl:56'),  # spec 15.3.8 3dexperience-configheader.srl:56
        ('put', 'u8', (162,), '15.3.8 3dexperience-configheader.srl:57'),  # spec 15.3.8 3dexperience-configheader.srl:57
        ('put', 'utf8', ('id',), '15.3.8 3dexperience-configheader.srl:58'),  # spec 15.3.8 3dexperience-configheader.srl:58
        ('put', 'u8', (0,), '15.3.8 3dexperience-configheader.srl:59'),  # spec 15.3.8 3dexperience-configheader.srl:59
        ('put', 'u8', (164,), '15.3.8 3dexperience-configheader.srl:60'),  # spec 15.3.8 3dexperience-configheader.srl:60
        ('put', 'utf8', ('name',), '15.3.8 3dexperience-configheader.srl:61'),  # spec 15.3.8 3dexperience-configheader.srl:61
        ('put', 'u8', (167,), '15.3.8 3dexperience-configheader.srl:62'),  # spec 15.3.8 3dexperience-configheader.srl:62
        ('put', 'utf8', ('Default',), '15.3.8 3dexperience-configheader.srl:63'),  # spec 15.3.8 3dexperience-configheader.srl:63
        ('put', 'u16be', (0,), '15.3.4 3dexperience-configheader.srl:67'),  # spec 15.3.4 3dexperience-configheader.srl:67
        ('put', 'u16be', (3953,), '15.3.4 3dexperience-configheader.srl:68'),  # spec 15.3.4 3dexperience-configheader.srl:68
        ('rep', 3949, 0, '15.3.4 3dexperience-configheader.srl:69'),  # spec 15.3.4 3dexperience-configheader.srl:69
    ),  # spec 15.3 3dexperience-configheader.srl
    'Contents/CMgr': (  # spec 15.2 cmgr.srl
        ('archive', 'start', 1, '15.2.7.1 cmgr.srl:31'),  # spec 15.2.7.1 cmgr.srl:31
        ('class', 'moConfigurationMgr_c', 1, None, '15.2.7.1 cmgr.srl:32'),  # spec 15.2.7.1 cmgr.srl:32
        ('put', 'u16', (0,), '15.2.7.1 cmgr.srl:33'),  # spec 15.2.7.1 cmgr.srl:33
        ('hex', '0000000000000040', '15.2.7.1 cmgr.srl:34'),  # spec 15.2.7.1 cmgr.srl:34
        ('put', 'i32', (-1,), '15.2.7.1 cmgr.srl:35'),  # spec 15.2.7.1 cmgr.srl:35
        ('put', 'u32', (0,), '15.2.7.1 cmgr.srl:36'),  # spec 15.2.7.1 cmgr.srl:36
        ('put', 'cstr', ('',), '15.2.7.1 cmgr.srl:37'),  # spec 15.2.7.1 cmgr.srl:37
        ('rep', 14, 0, '15.2.7.1 cmgr.srl:38'),  # spec 15.2.7.1 cmgr.srl:38
        ('put', 'u32', (101,), '15.2.7.1 cmgr.srl:8'),  # spec 15.2.7.1 cmgr.srl:8
        ('rep', 13, 0, '15.2.7.1 cmgr.srl:9'),  # spec 15.2.7.1 cmgr.srl:9
        ('put', 'u32', (17000,), '15.2.7.1 cmgr.srl:10'),  # spec 15.2.7.1 cmgr.srl:10
        ('rep', 8, 0, '15.2.7.1 cmgr.srl:11'),  # spec 15.2.7.1 cmgr.srl:11
        ('put', 'u32', (2024016,), '15.2.7.1 cmgr.srl:12'),  # spec 15.2.7.1 cmgr.srl:12
        ('put', 'u16', (0,), '15.2.7.1 cmgr.srl:13'),  # spec 15.2.7.1 cmgr.srl:13
        ('put', 'cstr', ('',), '15.2.7.1 cmgr.srl:14'),  # spec 15.2.7.1 cmgr.srl:14
        ('put', 'u8', (0,), '15.2.7.1 cmgr.srl:15'),  # spec 15.2.7.1 cmgr.srl:15
        ('put', 'u16', (65535, 0), '15.2.7.1 cmgr.srl:16'),  # spec 15.2.7.1 cmgr.srl:16
        ('put', 'u8', (3,), '15.2.7.1 cmgr.srl:17'),  # spec 15.2.7.1 cmgr.srl:17
        ('put', 'i32', (-1, -1), '15.2.7.1 cmgr.srl:18'),  # spec 15.2.7.1 cmgr.srl:18
        ('put', 'f32', (-1.0,), '15.2.7.1 cmgr.srl:19'),  # spec 15.2.7.1 cmgr.srl:19
        ('rep', 14, 0, '15.2.7.1 cmgr.srl:20'),  # spec 15.2.7.1 cmgr.srl:20
        ('put', 'u32', (1,), '15.2.7.1 cmgr.srl:21'),  # spec 15.2.7.1 cmgr.srl:21
        ('rep', 6, 0, '15.2.7.1 cmgr.srl:22'),  # spec 15.2.7.1 cmgr.srl:22
        ('put', 'i32', (-1,), '15.2.7.1 cmgr.srl:23'),  # spec 15.2.7.1 cmgr.srl:23
        ('put', 'u32', (('=', '$cmgr.created//4294967296'),), '15.2.7.1 cmgr.srl:24'),  # spec 15.2.7.1 cmgr.srl:24
        ('put', 'u32', (('=', '$cmgr.created%4294967296'),), '15.2.7.1 cmgr.srl:25'),  # spec 15.2.7.1 cmgr.srl:25
        ('put', 'u16', (2,), '15.2.7.1 cmgr.srl:26'),  # spec 15.2.7.1 cmgr.srl:26
        ('put', 'u32', (350108,), '15.2.7.1 cmgr.srl:27'),  # spec 15.2.7.1 cmgr.srl:27
        ('put', 'u32', (1,), '15.2.7.1 cmgr.srl:28'),  # spec 15.2.7.1 cmgr.srl:28
        ('class', 'moPartConfiguration_c', 1, None, '15.2.7.3 cmgr.srl:42'),  # spec 15.2.7.3 cmgr.srl:42
        ('class', 'moNodeName_c', 1, None, '15.2.7.3 cmgr.srl:43'),  # spec 15.2.7.3 cmgr.srl:43
        ('put', 'cstr', ('Default',), '15.2.7.3 cmgr.srl:44'),  # spec 15.2.7.3 cmgr.srl:44
        ('hex', '0000000000000040', '15.2.7.3 cmgr.srl:45'),  # spec 15.2.7.3 cmgr.srl:45
        ('hex', '0000000000020000', '15.2.7.3 cmgr.srl:46'),  # spec 15.2.7.3 cmgr.srl:46
        ('put', 'cstr', ('',), '15.2.7.3 cmgr.srl:47'),  # spec 15.2.7.3 cmgr.srl:47
        ('put', 'u32', (0,), '15.2.7.3 cmgr.srl:48'),  # spec 15.2.7.3 cmgr.srl:48
        ('class', 'moVisualProperties_c', 1, None, '15.2.9 visual-properties.srl:5'),  # spec 15.2.9 visual-properties.srl:5
        ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:6'),  # spec 15.2.9 visual-properties.srl:6
        ('put', 'u32', (0, 0), '15.2.9 visual-properties.srl:7'),  # spec 15.2.9 visual-properties.srl:7
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:8'),  # spec 15.2.9 visual-properties.srl:8
        ('put', 'cstr', ('Steel',), '15.2.9 visual-properties.srl:9'),  # spec 15.2.9 visual-properties.srl:9
        ('put', 'f64', (1.0, 1.0, 0.5, 0.3125), '15.2.9 visual-properties.srl:10'),  # spec 15.2.9 visual-properties.srl:10
        ('rep', 20, 0, '15.2.9 visual-properties.srl:11'),  # spec 15.2.9 visual-properties.srl:11
        ('put', 'u32', (1, 0, 1, 1, 1), '15.2.9 visual-properties.srl:12'),  # spec 15.2.9 visual-properties.srl:12
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:13'),  # spec 15.2.9 visual-properties.srl:13
        ('put', 'u32', (1, 1, 3, 0), '15.2.9 visual-properties.srl:14'),  # spec 15.2.9 visual-properties.srl:14
        ('put', 'cstr', ('defaultplastic',), '15.2.9 visual-properties.srl:15'),  # spec 15.2.9 visual-properties.srl:15
        ('put', 'u8', (3,), '15.2.9 visual-properties.srl:16'),  # spec 15.2.9 visual-properties.srl:16
        ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:17'),  # spec 15.2.9 visual-properties.srl:17
        ('put', 'f32', (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0), '15.2.9 visual-properties.srl:18'),  # spec 15.2.9 visual-properties.srl:18
        ('put', 'u32', (1,), '15.2.9 visual-properties.srl:19'),  # spec 15.2.9 visual-properties.srl:19
        ('put', 'f32', (0.15, 0.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0), '15.2.9 visual-properties.srl:20'),  # spec 15.2.9 visual-properties.srl:20
        ('put', 'cstr', (('$', 'cmgr.texture'),), '15.2.9 visual-properties.srl:21'),  # spec 15.2.9 visual-properties.srl:21
        ('put', 'u32', (16777215,), '15.2.9 visual-properties.srl:22'),  # spec 15.2.9 visual-properties.srl:22
        ('put', 'f32', (0.6, 1.0), '15.2.9 visual-properties.srl:23'),  # spec 15.2.9 visual-properties.srl:23
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:24'),  # spec 15.2.9 visual-properties.srl:24
        ('put', 'f32', (0.001, 0.001, 0.0), '15.2.9 visual-properties.srl:25'),  # spec 15.2.9 visual-properties.srl:25
        ('put', 'u16', (320, 0), '15.2.9 visual-properties.srl:26'),  # spec 15.2.9 visual-properties.srl:26
        ('put', 'f32', (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 90.0, 1.0, -1.0, -1.0), '15.2.9 visual-properties.srl:27'),  # spec 15.2.9 visual-properties.srl:27
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:28'),  # spec 15.2.9 visual-properties.srl:28
        ('put', 'u32', (0,), '15.2.9 visual-properties.srl:29'),  # spec 15.2.9 visual-properties.srl:29
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:30'),  # spec 15.2.9 visual-properties.srl:30
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:31'),  # spec 15.2.9 visual-properties.srl:31
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:32'),  # spec 15.2.9 visual-properties.srl:32
        ('rep', 92, 0, '15.2.9 visual-properties.srl:33'),  # spec 15.2.9 visual-properties.srl:33
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:34'),  # spec 15.2.9 visual-properties.srl:34
        ('rep', 8, 0, '15.2.9 visual-properties.srl:35'),  # spec 15.2.9 visual-properties.srl:35
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:36'),  # spec 15.2.9 visual-properties.srl:36
        ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:37'),  # spec 15.2.9 visual-properties.srl:37
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:38'),  # spec 15.2.9 visual-properties.srl:38
        ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:39'),  # spec 15.2.9 visual-properties.srl:39
        ('put', 'i32', (-1,), '15.2.9 visual-properties.srl:40'),  # spec 15.2.9 visual-properties.srl:40
        ('rep', 12, 0, '15.2.9 visual-properties.srl:41'),  # spec 15.2.9 visual-properties.srl:41
        ('rep', 8, 0, '15.2.7.3 cmgr.srl:50'),  # spec 15.2.7.3 cmgr.srl:50
        ('put', 'u32', (101,), '15.2.7.1 cmgr.srl:8'),  # spec 15.2.7.1 cmgr.srl:8
        ('rep', 13, 0, '15.2.7.1 cmgr.srl:9'),  # spec 15.2.7.1 cmgr.srl:9
        ('put', 'u32', (17000,), '15.2.7.1 cmgr.srl:10'),  # spec 15.2.7.1 cmgr.srl:10
        ('rep', 8, 0, '15.2.7.1 cmgr.srl:11'),  # spec 15.2.7.1 cmgr.srl:11
        ('put', 'u32', (2024016,), '15.2.7.1 cmgr.srl:12'),  # spec 15.2.7.1 cmgr.srl:12
        ('put', 'u16', (0,), '15.2.7.1 cmgr.srl:13'),  # spec 15.2.7.1 cmgr.srl:13
        ('put', 'cstr', ('',), '15.2.7.1 cmgr.srl:14'),  # spec 15.2.7.1 cmgr.srl:14
        ('put', 'u8', (0,), '15.2.7.1 cmgr.srl:15'),  # spec 15.2.7.1 cmgr.srl:15
        ('put', 'u16', (65535, 0), '15.2.7.1 cmgr.srl:16'),  # spec 15.2.7.1 cmgr.srl:16
        ('put', 'u8', (3,), '15.2.7.1 cmgr.srl:17'),  # spec 15.2.7.1 cmgr.srl:17
        ('put', 'i32', (-1, -1), '15.2.7.1 cmgr.srl:18'),  # spec 15.2.7.1 cmgr.srl:18
        ('put', 'f32', (-1.0,), '15.2.7.1 cmgr.srl:19'),  # spec 15.2.7.1 cmgr.srl:19
        ('rep', 14, 0, '15.2.7.1 cmgr.srl:20'),  # spec 15.2.7.1 cmgr.srl:20
        ('put', 'u32', (1,), '15.2.7.1 cmgr.srl:21'),  # spec 15.2.7.1 cmgr.srl:21
        ('rep', 6, 0, '15.2.7.1 cmgr.srl:22'),  # spec 15.2.7.1 cmgr.srl:22
        ('put', 'i32', (-1,), '15.2.7.1 cmgr.srl:23'),  # spec 15.2.7.1 cmgr.srl:23
        ('put', 'u32', (('=', '$cmgr.created//4294967296'),), '15.2.7.1 cmgr.srl:24'),  # spec 15.2.7.1 cmgr.srl:24
        ('put', 'u32', (('=', '$cmgr.created%4294967296'),), '15.2.7.1 cmgr.srl:25'),  # spec 15.2.7.1 cmgr.srl:25
        ('put', 'u16', (2,), '15.2.7.1 cmgr.srl:26'),  # spec 15.2.7.1 cmgr.srl:26
        ('put', 'u32', (350108,), '15.2.7.1 cmgr.srl:27'),  # spec 15.2.7.1 cmgr.srl:27
        ('put', 'u32', (1,), '15.2.7.1 cmgr.srl:28'),  # spec 15.2.7.1 cmgr.srl:28
        ('put', 'cstr', ('',), '15.2.7.3 cmgr.srl:52'),  # spec 15.2.7.3 cmgr.srl:52
        ('put', 'i32', (-1,), '15.2.7.3 cmgr.srl:53'),  # spec 15.2.7.3 cmgr.srl:53
        ('put', 'u32', (2151678336,), '15.2.7.3 cmgr.srl:54'),  # spec 15.2.7.3 cmgr.srl:54
        ('put', 'cstr', ('',), '15.2.7.3 cmgr.srl:55'),  # spec 15.2.7.3 cmgr.srl:55
        ('put', 'u32', (('=', '$hdr.next_id-1'),), '15.2.7.3 cmgr.srl:56'),  # spec 15.2.7.3 cmgr.srl:56
        ('put', 'u32', (('$', 'doc.stamp'),), '15.2.7.3 cmgr.srl:57'),  # spec 15.2.7.3 cmgr.srl:57
        ('rep', 100, 0, '15.2.7.3 cmgr.srl:58'),  # spec 15.2.7.3 cmgr.srl:58
        ('put', 'u32', (1,), '15.2.7.3 cmgr.srl:59'),  # spec 15.2.7.3 cmgr.srl:59
        ('rep', 40, 0, '15.2.7.3 cmgr.srl:60'),  # spec 15.2.7.3 cmgr.srl:60
        ('put', 'cstr', ('',), '15.2.7.3 cmgr.srl:61'),  # spec 15.2.7.3 cmgr.srl:61
        ('put', 'cstr', ('',), '15.2.7.3 cmgr.srl:62'),  # spec 15.2.7.3 cmgr.srl:62
        ('rep', 28, 0, '15.2.7.3 cmgr.srl:63'),  # spec 15.2.7.3 cmgr.srl:63
        ('put', 'f64', (1.0, 0.0, 0.0), '15.2.7.3 cmgr.srl:64'),  # spec 15.2.7.3 cmgr.srl:64
        ('put', 'f64', (0.0, 1.0, 0.0), '15.2.7.3 cmgr.srl:65'),  # spec 15.2.7.3 cmgr.srl:65
        ('put', 'f64', (0.0, 0.0, 1.0), '15.2.7.3 cmgr.srl:66'),  # spec 15.2.7.3 cmgr.srl:66
        ('put', 'u32', (1,), '15.2.7.3 cmgr.srl:67'),  # spec 15.2.7.3 cmgr.srl:67
        ('put', 'u16', (0,), '15.2.7.3 cmgr.srl:68'),  # spec 15.2.7.3 cmgr.srl:68
        ('put', 'u32', (631170000,), '15.2.7.3 cmgr.srl:69'),  # spec 15.2.7.3 cmgr.srl:69
        ('put', 'u32', (0,), '15.2.7.3 cmgr.srl:70'),  # spec 15.2.7.3 cmgr.srl:70
        ('put', 'u32', (('=', 'len($bodies)'),), '15.2.7.4 cmgr.srl:74'),  # spec 15.2.7.4 cmgr.srl:74
        ('put', 'u32', (0,), '15.2.7.4 cmgr.srl:75'),  # spec 15.2.7.4 cmgr.srl:75
        ('put', 'u32', (17000,), '15.2.7.4 cmgr.srl:76'),  # spec 15.2.7.4 cmgr.srl:76
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:77'),  # spec 15.2.7.4 cmgr.srl:77
        ('rep', 6, 0, '15.2.7.4 cmgr.srl:78'),  # spec 15.2.7.4 cmgr.srl:78
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:79'),  # spec 15.2.7.4 cmgr.srl:79
        ('rep', 8, 0, '15.2.7.4 cmgr.srl:80'),  # spec 15.2.7.4 cmgr.srl:80
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:81'),  # spec 15.2.7.4 cmgr.srl:81
        ('put', 'f32', (-1.0, -1.0), '15.2.7.4 cmgr.srl:82'),  # spec 15.2.7.4 cmgr.srl:82
        ('rep', 8, 0, '15.2.7.4 cmgr.srl:83'),  # spec 15.2.7.4 cmgr.srl:83
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:84'),  # spec 15.2.7.4 cmgr.srl:84
        ('rep', 28, 0, '15.2.7.4 cmgr.srl:85'),  # spec 15.2.7.4 cmgr.srl:85
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:86'),  # spec 15.2.7.4 cmgr.srl:86
        ('rep', 4, 0, '15.2.7.4 cmgr.srl:87'),  # spec 15.2.7.4 cmgr.srl:87
        ('put', 'i32', (-1,), '15.2.7.4 cmgr.srl:88'),  # spec 15.2.7.4 cmgr.srl:88
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:89'),  # spec 15.2.7.4 cmgr.srl:89
        ('rep', 12, 0, '15.2.7.4 cmgr.srl:90'),  # spec 15.2.7.4 cmgr.srl:90
        ('put', 'u32', (('=', 'len($bodies)'),), '15.2.7.4 cmgr.srl:91'),  # spec 15.2.7.4 cmgr.srl:91
        ('for', 'b', ('$', 'bodies'), False, (  # spec 15.2.7.4 cmgr.srl:92
            ('put', 'u32', (('$', 'b.id'),), '15.2.7.4 cmgr.srl:93'),  # spec 15.2.7.4 cmgr.srl:93
            ('put', 'u32', (0,), '15.2.7.4 cmgr.srl:94'),  # spec 15.2.7.4 cmgr.srl:94
        ), '15.2.7.4 cmgr.srl:92'),  # spec 15.2.7.4 cmgr.srl:92
        ('rep', 40, 0, '15.2.7.4 cmgr.srl:96'),  # spec 15.2.7.4 cmgr.srl:96
        ('put', 'u32', (('=', 'len($bodies)'),), '15.2.7.4 cmgr.srl:97'),  # spec 15.2.7.4 cmgr.srl:97
        ('for', 'b', ('$', 'bodies'), False, (  # spec 15.2.7.4 cmgr.srl:98
            ('put', 'u32', (('$', 'b.id'),), '15.2.7.4 cmgr.srl:99'),  # spec 15.2.7.4 cmgr.srl:99
            ('class', 'moLinkedAtomIdNode_c', 1, None, '15.2.7.4 cmgr.srl:100'),  # spec 15.2.7.4 cmgr.srl:100
            ('put', 'u32', (('$', 'b.id'),), '15.2.7.4 cmgr.srl:101'),  # spec 15.2.7.4 cmgr.srl:101
            ('put', 'u16', (1,), '15.2.7.4 cmgr.srl:102'),  # spec 15.2.7.4 cmgr.srl:102
            ('put', 'u32', (('$', 'b.feature'),), '15.2.7.4 cmgr.srl:103'),  # spec 15.2.7.4 cmgr.srl:103
            ('rep', 18, 0, '15.2.7.4 cmgr.srl:104'),  # spec 15.2.7.4 cmgr.srl:104
        ), '15.2.7.4 cmgr.srl:98'),  # spec 15.2.7.4 cmgr.srl:98
        ('rep', 16, 0, '15.2.7.4 cmgr.srl:106'),  # spec 15.2.7.4 cmgr.srl:106
        ('put', 'u32', (2,), '15.2.7.4 cmgr.srl:107'),  # spec 15.2.7.4 cmgr.srl:107
        ('rep', 14, 0, '15.2.7.4 cmgr.srl:108'),  # spec 15.2.7.4 cmgr.srl:108
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:109'),  # spec 15.2.7.4 cmgr.srl:109
        ('put', 'i32', (-1,), '15.2.7.4 cmgr.srl:110'),  # spec 15.2.7.4 cmgr.srl:110
        ('rep', 44, 0, '15.2.7.4 cmgr.srl:111'),  # spec 15.2.7.4 cmgr.srl:111
        ('put', 'f64', (-1.0,), '15.2.7.4 cmgr.srl:112'),  # spec 15.2.7.4 cmgr.srl:112
        ('rep', 18, 0, '15.2.7.4 cmgr.srl:113'),  # spec 15.2.7.4 cmgr.srl:113
        ('put', 'i32', (-1,), '15.2.7.4 cmgr.srl:114'),  # spec 15.2.7.4 cmgr.srl:114
        ('put', 'u32', (('=', 'len($bodies)'),), '15.2.7.4 cmgr.srl:115'),  # spec 15.2.7.4 cmgr.srl:115
        ('for', 'b', ('$', 'bodies'), True, (  # spec 15.2.7.4 cmgr.srl:116
            ('put', 'u32', (('$', 'b.id'),), '15.2.7.4 cmgr.srl:117'),  # spec 15.2.7.4 cmgr.srl:117
            ('put', 'u32', (0,), '15.2.7.4 cmgr.srl:118'),  # spec 15.2.7.4 cmgr.srl:118
        ), '15.2.7.4 cmgr.srl:116'),  # spec 15.2.7.4 cmgr.srl:116
        ('rep', 8, 0, '15.2.7.4 cmgr.srl:120'),  # spec 15.2.7.4 cmgr.srl:120
        ('put', 'i32', (-1, -1), '15.2.7.4 cmgr.srl:121'),  # spec 15.2.7.4 cmgr.srl:121
        ('rep', 8, 0, '15.2.7.4 cmgr.srl:122'),  # spec 15.2.7.4 cmgr.srl:122
        ('put', 'u16', (4,), '15.2.7.4 cmgr.srl:123'),  # spec 15.2.7.4 cmgr.srl:123
        ('put', 'u32', (1,), '15.2.7.4 cmgr.srl:124'),  # spec 15.2.7.4 cmgr.srl:124
        ('put', 'u16', (1, 4), '15.2.7.4 cmgr.srl:125'),  # spec 15.2.7.4 cmgr.srl:125
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.7.5 cmgr.srl:128
            ('put', 'u32', (1,), '15.2.7.5 cmgr.srl:129'),  # spec 15.2.7.5 cmgr.srl:129
            ('class', 'moExtObject_c', 1, None, '15.2.7.5 cmgr.srl:130'),  # spec 15.2.7.5 cmgr.srl:130
            ('class', 'moCStringHandle_c', 1, None, '15.2.7.5 cmgr.srl:131'),  # spec 15.2.7.5 cmgr.srl:131
            ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:132'),  # spec 15.2.7.5 cmgr.srl:132
            ('class', 'moCStringHandle_c', 1, None, '15.2.7.5 cmgr.srl:133'),  # spec 15.2.7.5 cmgr.srl:133
            ('put', 'cstr', (('$', 'doc.name'),), '15.2.7.5 cmgr.srl:134'),  # spec 15.2.7.5 cmgr.srl:134
            ('hex', '020000', '15.2.7.5 cmgr.srl:135'),  # spec 15.2.7.5 cmgr.srl:135
            ('put', 'u32', (('$', 'doc.created'),), '15.2.7.5 cmgr.srl:136'),  # spec 15.2.7.5 cmgr.srl:136
            ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:137'),  # spec 15.2.7.5 cmgr.srl:137
            ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:138'),  # spec 15.2.7.5 cmgr.srl:138
            ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:139'),  # spec 15.2.7.5 cmgr.srl:139
            ('rep', 18, 0, '15.2.7.5 cmgr.srl:140'),  # spec 15.2.7.5 cmgr.srl:140
            ('put', 'cstr', ('Default',), '15.2.7.5 cmgr.srl:141'),  # spec 15.2.7.5 cmgr.srl:141
            ('rep', 16, 0, '15.2.7.5 cmgr.srl:142'),  # spec 15.2.7.5 cmgr.srl:142
        ), (  # spec 15.2.7.5 cmgr.srl:128
            ('put', 'u32', (0,), '15.2.7.5 cmgr.srl:144'),  # spec 15.2.7.5 cmgr.srl:144
        ), '15.2.7.5 cmgr.srl:128'),  # spec 15.2.7.5 cmgr.srl:128
        ('rep', 4, 0, '15.2.7.5 cmgr.srl:146'),  # spec 15.2.7.5 cmgr.srl:146
        ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:147'),  # spec 15.2.7.5 cmgr.srl:147
        ('rep', 4, 0, '15.2.7.5 cmgr.srl:148'),  # spec 15.2.7.5 cmgr.srl:148
        ('class', 'suObList', 1, None, '15.2.7.5 cmgr.srl:149'),  # spec 15.2.7.5 cmgr.srl:149
        ('put', 'u16', (0,), '15.2.7.5 cmgr.srl:150'),  # spec 15.2.7.5 cmgr.srl:150
        ('put', 'u32', (('=', 'len($bodies)'),), '15.2.7.5 cmgr.srl:151'),  # spec 15.2.7.5 cmgr.srl:151
        ('for', 'b', ('$', 'bodies'), True, (  # spec 15.2.7.5 cmgr.srl:152
            ('put', 'u32', (('$', 'b.feature'),), '15.2.7.5 cmgr.srl:153'),  # spec 15.2.7.5 cmgr.srl:153
            ('put', 'u32', (('=', '$b.time//4294967296'),), '15.2.7.5 cmgr.srl:154'),  # spec 15.2.7.5 cmgr.srl:154
            ('put', 'u32', (('=', '$b.time%4294967296'),), '15.2.7.5 cmgr.srl:155'),  # spec 15.2.7.5 cmgr.srl:155
        ), '15.2.7.5 cmgr.srl:152'),  # spec 15.2.7.5 cmgr.srl:152
        ('rep', 8, 0, '15.2.7.5 cmgr.srl:157'),  # spec 15.2.7.5 cmgr.srl:157
        ('put', 'u32', (1,), '15.2.7.5 cmgr.srl:158'),  # spec 15.2.7.5 cmgr.srl:158
        ('rep', 8, 0, '15.2.7.5 cmgr.srl:159'),  # spec 15.2.7.5 cmgr.srl:159
        ('class', 'suObList', 1, None, '15.2.7.5 cmgr.srl:160'),  # spec 15.2.7.5 cmgr.srl:160
        ('put', 'u16', (0,), '15.2.7.5 cmgr.srl:161'),  # spec 15.2.7.5 cmgr.srl:161
        ('rep', 26, 0, '15.2.7.5 cmgr.srl:162'),  # spec 15.2.7.5 cmgr.srl:162
        ('put', 'u32', (2,), '15.2.7.5 cmgr.srl:163'),  # spec 15.2.7.5 cmgr.srl:163
        ('rep', 4, 0, '15.2.7.5 cmgr.srl:164'),  # spec 15.2.7.5 cmgr.srl:164
        ('put', 'cstr', ('',), '15.2.7.5 cmgr.srl:165'),  # spec 15.2.7.5 cmgr.srl:165
        ('rep', 12, 0, '15.2.7.5 cmgr.srl:166'),  # spec 15.2.7.5 cmgr.srl:166
        ('put', 'i32', (-1,), '15.2.7.5 cmgr.srl:167'),  # spec 15.2.7.5 cmgr.srl:167
        ('rep', 4, 0, '15.2.7.5 cmgr.srl:168'),  # spec 15.2.7.5 cmgr.srl:168
    ),  # spec 15.2 cmgr.srl
    'Contents/CMgrHdr2': (  # spec 15.2 cmgrhdr2.srl
        ('archive', 'start', 1, '15.2.3.1 cmgrhdr2.srl:5'),  # spec 15.2.3.1 cmgrhdr2.srl:5
        ('class', 'dmConfigMgrHeader_c', 1, None, '15.2.3.1 cmgrhdr2.srl:6'),  # spec 15.2.3.1 cmgrhdr2.srl:6
        ('put', 'u16', (1,), '15.2.3.1 cmgrhdr2.srl:7'),  # spec 15.2.3.1 cmgrhdr2.srl:7
        ('class', 'dmConfigHeader_c', 1, None, '15.2.3.1 cmgrhdr2.srl:8'),  # spec 15.2.3.1 cmgrhdr2.srl:8
        ('put', 'u32', (1,), '15.2.3.1 cmgrhdr2.srl:9'),  # spec 15.2.3.1 cmgrhdr2.srl:9
        ('put', 'cstr', ('Default',), '15.2.3.1 cmgrhdr2.srl:10'),  # spec 15.2.3.1 cmgrhdr2.srl:10
        ('put', 'u32', (0,), '15.2.3.1 cmgrhdr2.srl:11'),  # spec 15.2.3.1 cmgrhdr2.srl:11
        ('put', 'u32', (('$', 'doc.stamp'),), '15.2.3.1 cmgrhdr2.srl:12'),  # spec 15.2.3.1 cmgrhdr2.srl:12
        ('put', 'cstr', ('Default',), '15.2.3.1 cmgrhdr2.srl:13'),  # spec 15.2.3.1 cmgrhdr2.srl:13
        ('put', 'i32', (-1,), '15.2.3.1 cmgrhdr2.srl:14'),  # spec 15.2.3.1 cmgrhdr2.srl:14
        ('put', 'u32', (0,), '15.2.3.1 cmgrhdr2.srl:15'),  # spec 15.2.3.1 cmgrhdr2.srl:15
        ('put', 'cstr', ('',), '15.2.3.1 cmgrhdr2.srl:16'),  # spec 15.2.3.1 cmgrhdr2.srl:16
        ('put', 'cstr', ('',), '15.2.3.1 cmgrhdr2.srl:17'),  # spec 15.2.3.1 cmgrhdr2.srl:17
        ('put', 'u32', (2151678336,), '15.2.3.1 cmgrhdr2.srl:18'),  # spec 15.2.3.1 cmgrhdr2.srl:18
        ('put', 'u32', (0,), '15.2.3.1 cmgrhdr2.srl:19'),  # spec 15.2.3.1 cmgrhdr2.srl:19
        ('put', 'u32', (('=', '101+len($features)'),), '15.2.3.1 cmgrhdr2.srl:20'),  # spec 15.2.3.1 cmgrhdr2.srl:20
        ('put', 'u32', (101,), '15.2.3.1 cmgrhdr2.srl:21'),  # spec 15.2.3.1 cmgrhdr2.srl:21
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.3.1 cmgrhdr2.srl:22
            ('put', 'u32', (('$', 'doc.unix'),), '15.2.3.1 cmgrhdr2.srl:23'),  # spec 15.2.3.1 cmgrhdr2.srl:23
        ), (  # spec 15.2.3.1 cmgrhdr2.srl:22
            ('put', 'u32', (('$', 'tpl.unix2'),), '15.2.3.1 cmgrhdr2.srl:25'),  # spec 15.2.3.1 cmgrhdr2.srl:25
        ), '15.2.3.1 cmgrhdr2.srl:22'),  # spec 15.2.3.1 cmgrhdr2.srl:22
        ('put', 'u32', (2,), '15.2.3.1 cmgrhdr2.srl:27'),  # spec 15.2.3.1 cmgrhdr2.srl:27
    ),  # spec 15.2 cmgrhdr2.srl
    'Contents/CnfgObjs': (  # spec 15.1 cnfgobjs.srl
        ('put', 'u16', (0,), '15.1.7 cnfgobjs.srl:5'),  # spec 15.1.7 cnfgobjs.srl:5
        ('put', 'u16', (0,), '15.1.7 cnfgobjs.srl:6'),  # spec 15.1.7 cnfgobjs.srl:6
        ('put', 'cstr', ('',), '15.1.7 cnfgobjs.srl:7'),  # spec 15.1.7 cnfgobjs.srl:7
        ('put', 'cstr', ('',), '15.1.7 cnfgobjs.srl:8'),  # spec 15.1.7 cnfgobjs.srl:8
    ),  # spec 15.1 cnfgobjs.srl
    'Contents/Config-0': (  # spec 15.4 config-0.srl
        ('archive', 'start', 2, '15.4.1 config-0.srl:7'),  # spec 15.4.1 config-0.srl:7
        ('class', 'moPart_c', 1, None, '15.4.1 config-0.srl:8'),  # spec 15.4.1 config-0.srl:8
        ('sized', 'u32', 'settings_size', (  # spec 15.4.1 config-0.srl:9
            ('put', 'u32', (0, 17000), '15.4.1 config-0.srl:10'),  # spec 15.4.1 config-0.srl:10
            ('class', 'moNodeName_c', 1, None, '15.4.1 config-0.srl:12'),  # spec 15.4.1 config-0.srl:12
            ('put', 'cstr', (('$', 'doc.name'),), '15.4.1 config-0.srl:13'),  # spec 15.4.1 config-0.srl:13
            ('put', 'u32', (0, 1073741824, 0, ('=', '256+32*int($model.solid)')), '15.4.1 config-0.srl:14'),  # spec 15.4.1 config-0.srl:14
            ('put', 'cstr', ('',), '15.4.1 config-0.srl:15'),  # spec 15.4.1 config-0.srl:15
            ('put', 'u32', (0,), '15.4.1 config-0.srl:16'),  # spec 15.4.1 config-0.srl:16
            ('class', 'moVisualProperties_c', 1, None, '15.2.9 visual-properties.srl:5'),  # spec 15.2.9 visual-properties.srl:5
            ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:6'),  # spec 15.2.9 visual-properties.srl:6
            ('put', 'u32', (0, 0), '15.2.9 visual-properties.srl:7'),  # spec 15.2.9 visual-properties.srl:7
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:8'),  # spec 15.2.9 visual-properties.srl:8
            ('put', 'cstr', ('Steel',), '15.2.9 visual-properties.srl:9'),  # spec 15.2.9 visual-properties.srl:9
            ('put', 'f64', (1.0, 1.0, 0.5, 0.3125), '15.2.9 visual-properties.srl:10'),  # spec 15.2.9 visual-properties.srl:10
            ('rep', 20, 0, '15.2.9 visual-properties.srl:11'),  # spec 15.2.9 visual-properties.srl:11
            ('put', 'u32', (1, 0, 1, 1, 1), '15.2.9 visual-properties.srl:12'),  # spec 15.2.9 visual-properties.srl:12
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:13'),  # spec 15.2.9 visual-properties.srl:13
            ('put', 'u32', (1, 1, 3, 0), '15.2.9 visual-properties.srl:14'),  # spec 15.2.9 visual-properties.srl:14
            ('put', 'cstr', ('defaultplastic',), '15.2.9 visual-properties.srl:15'),  # spec 15.2.9 visual-properties.srl:15
            ('put', 'u8', (3,), '15.2.9 visual-properties.srl:16'),  # spec 15.2.9 visual-properties.srl:16
            ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:17'),  # spec 15.2.9 visual-properties.srl:17
            ('put', 'f32', (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0), '15.2.9 visual-properties.srl:18'),  # spec 15.2.9 visual-properties.srl:18
            ('put', 'u32', (1,), '15.2.9 visual-properties.srl:19'),  # spec 15.2.9 visual-properties.srl:19
            ('put', 'f32', (0.15, 0.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0), '15.2.9 visual-properties.srl:20'),  # spec 15.2.9 visual-properties.srl:20
            ('put', 'cstr', (('$', 'cmgr.texture'),), '15.2.9 visual-properties.srl:21'),  # spec 15.2.9 visual-properties.srl:21
            ('put', 'u32', (16777215,), '15.2.9 visual-properties.srl:22'),  # spec 15.2.9 visual-properties.srl:22
            ('put', 'f32', (0.6, 1.0), '15.2.9 visual-properties.srl:23'),  # spec 15.2.9 visual-properties.srl:23
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:24'),  # spec 15.2.9 visual-properties.srl:24
            ('put', 'f32', (0.001, 0.001, 0.0), '15.2.9 visual-properties.srl:25'),  # spec 15.2.9 visual-properties.srl:25
            ('put', 'u16', (320, 0), '15.2.9 visual-properties.srl:26'),  # spec 15.2.9 visual-properties.srl:26
            ('put', 'f32', (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 90.0, 1.0, -1.0, -1.0), '15.2.9 visual-properties.srl:27'),  # spec 15.2.9 visual-properties.srl:27
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:28'),  # spec 15.2.9 visual-properties.srl:28
            ('put', 'u32', (0,), '15.2.9 visual-properties.srl:29'),  # spec 15.2.9 visual-properties.srl:29
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:30'),  # spec 15.2.9 visual-properties.srl:30
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:31'),  # spec 15.2.9 visual-properties.srl:31
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:32'),  # spec 15.2.9 visual-properties.srl:32
            ('rep', 92, 0, '15.2.9 visual-properties.srl:33'),  # spec 15.2.9 visual-properties.srl:33
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:34'),  # spec 15.2.9 visual-properties.srl:34
            ('rep', 8, 0, '15.2.9 visual-properties.srl:35'),  # spec 15.2.9 visual-properties.srl:35
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:36'),  # spec 15.2.9 visual-properties.srl:36
            ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:37'),  # spec 15.2.9 visual-properties.srl:37
            ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:38'),  # spec 15.2.9 visual-properties.srl:38
            ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:39'),  # spec 15.2.9 visual-properties.srl:39
            ('put', 'i32', (-1,), '15.2.9 visual-properties.srl:40'),  # spec 15.2.9 visual-properties.srl:40
            ('rep', 12, 0, '15.2.9 visual-properties.srl:41'),  # spec 15.2.9 visual-properties.srl:41
            ('class', 'moUnitsTable_c', 1, None, '15.4.4 config-0.srl:27'),  # spec 15.4.4 config-0.srl:27
            ('hex', '10', '15.4.4 config-0.srl:28'),  # spec 15.4.4 config-0.srl:28
            ('put', 'u8', (0,), '15.4.4 config-0.srl:29'),  # spec 15.4.4 config-0.srl:29
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.4 config-0.srl:30'),  # spec 15.4.4 config-0.srl:30
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:31'),  # spec 15.4.4 config-0.srl:31
            ('put', 'f64', (0.254,), '15.4.4 config-0.srl:32'),  # spec 15.4.4 config-0.srl:32
            ('put', 'u32', (4, 1), '15.4.4 config-0.srl:33'),  # spec 15.4.4 config-0.srl:33
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:34'),  # spec 15.4.4 config-0.srl:34
            ('put', 'u32', (0, 0, 1, 1), '15.4.4 config-0.srl:35'),  # spec 15.4.4 config-0.srl:35
            ('put', 'f64', (('$', 'config0.length_memo'),), '15.4.4 config-0.srl:36'),  # spec 15.4.4 config-0.srl:36
            ('put', 'u32', (0, 0), '15.4.4 config-0.srl:37'),  # spec 15.4.4 config-0.srl:37
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.4 config-0.srl:38'),  # spec 15.4.4 config-0.srl:38
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:39'),  # spec 15.4.4 config-0.srl:39
            ('put', 'f64', (1.0,), '15.4.4 config-0.srl:40'),  # spec 15.4.4 config-0.srl:40
            ('put', 'u32', (1, 1), '15.4.4 config-0.srl:41'),  # spec 15.4.4 config-0.srl:41
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:42'),  # spec 15.4.4 config-0.srl:42
            ('put', 'u32', (2, 0, 1, 1), '15.4.4 config-0.srl:43'),  # spec 15.4.4 config-0.srl:43
            ('rep', 14, 0, '15.4.4 config-0.srl:44'),  # spec 15.4.4 config-0.srl:44
            ('put', 'u32', (3,), '15.4.4 config-0.srl:45'),  # spec 15.4.4 config-0.srl:45
            ('class', 'moAngleUserUnits_c', 1, None, '15.4.4 config-0.srl:46'),  # spec 15.4.4 config-0.srl:46
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:47'),  # spec 15.4.4 config-0.srl:47
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:48'),  # spec 15.4.4 config-0.srl:48
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:49'),  # spec 15.4.4 config-0.srl:49
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:50'),  # spec 15.4.4 config-0.srl:50
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:51'),  # spec 15.4.4 config-0.srl:51
            ('rep', 16, 0, '15.4.4 config-0.srl:52'),  # spec 15.4.4 config-0.srl:52
            ('class', 'moNumberUserUnits_c', 1, None, '15.4.4 config-0.srl:53'),  # spec 15.4.4 config-0.srl:53
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:54'),  # spec 15.4.4 config-0.srl:54
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:55'),  # spec 15.4.4 config-0.srl:55
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:56'),  # spec 15.4.4 config-0.srl:56
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:57'),  # spec 15.4.4 config-0.srl:57
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:58'),  # spec 15.4.4 config-0.srl:58
            ('rep', 14, 0, '15.4.4 config-0.srl:59'),  # spec 15.4.4 config-0.srl:59
            ('class', 'moDensityUnits_c', 1, None, '15.4.4 config-0.srl:60'),  # spec 15.4.4 config-0.srl:60
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:61'),  # spec 15.4.4 config-0.srl:61
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:62'),  # spec 15.4.4 config-0.srl:62
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:63'),  # spec 15.4.4 config-0.srl:63
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:64'),  # spec 15.4.4 config-0.srl:64
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:65'),  # spec 15.4.4 config-0.srl:65
            ('rep', 14, 0, '15.4.4 config-0.srl:66'),  # spec 15.4.4 config-0.srl:66
            ('put', 'u32', (65539, 768), '15.4.4 config-0.srl:67'),  # spec 15.4.4 config-0.srl:67
            ('rep', 3, 0, '15.4.4 config-0.srl:68'),  # spec 15.4.4 config-0.srl:68
            ('class', 'moFloatNumberUserUnits_c', 1, None, '15.4.4 config-0.srl:69'),  # spec 15.4.4 config-0.srl:69
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:70'),  # spec 15.4.4 config-0.srl:70
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:71'),  # spec 15.4.4 config-0.srl:71
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:72'),  # spec 15.4.4 config-0.srl:72
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:73'),  # spec 15.4.4 config-0.srl:73
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:74'),  # spec 15.4.4 config-0.srl:74
            ('rep', 14, 0, '15.4.4 config-0.srl:75'),  # spec 15.4.4 config-0.srl:75
            ('class', 'moSpringConstantUnits_c', 1, None, '15.4.4 config-0.srl:76'),  # spec 15.4.4 config-0.srl:76
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:77'),  # spec 15.4.4 config-0.srl:77
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:78'),  # spec 15.4.4 config-0.srl:78
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:79'),  # spec 15.4.4 config-0.srl:79
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:80'),  # spec 15.4.4 config-0.srl:80
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:81'),  # spec 15.4.4 config-0.srl:81
            ('rep', 14, 0, '15.4.4 config-0.srl:82'),  # spec 15.4.4 config-0.srl:82
            ('class', 'moUnitSysUnits_c', 1, None, '15.4.4 config-0.srl:83'),  # spec 15.4.4 config-0.srl:83
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:84'),  # spec 15.4.4 config-0.srl:84
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:85'),  # spec 15.4.4 config-0.srl:85
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:86'),  # spec 15.4.4 config-0.srl:86
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:87'),  # spec 15.4.4 config-0.srl:87
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:88'),  # spec 15.4.4 config-0.srl:88
            ('rep', 14, 0, '15.4.4 config-0.srl:89'),  # spec 15.4.4 config-0.srl:89
            ('hex', '04', '15.4.4 config-0.srl:90'),  # spec 15.4.4 config-0.srl:90
            ('put', 'u8', (0,), '15.4.4 config-0.srl:91'),  # spec 15.4.4 config-0.srl:91
            ('class', 'moForceUnits_c', 1, None, '15.4.4 config-0.srl:92'),  # spec 15.4.4 config-0.srl:92
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:93'),  # spec 15.4.4 config-0.srl:93
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:94'),  # spec 15.4.4 config-0.srl:94
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:95'),  # spec 15.4.4 config-0.srl:95
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:96'),  # spec 15.4.4 config-0.srl:96
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:97'),  # spec 15.4.4 config-0.srl:97
            ('rep', 14, 0, '15.4.4 config-0.srl:98'),  # spec 15.4.4 config-0.srl:98
            ('hex', '02', '15.4.4 config-0.srl:99'),  # spec 15.4.4 config-0.srl:99
            ('put', 'u8', (0,), '15.4.4 config-0.srl:100'),  # spec 15.4.4 config-0.srl:100
            ('class', 'moStressUnits_c', 1, None, '15.4.4 config-0.srl:101'),  # spec 15.4.4 config-0.srl:101
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:102'),  # spec 15.4.4 config-0.srl:102
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:103'),  # spec 15.4.4 config-0.srl:103
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:104'),  # spec 15.4.4 config-0.srl:104
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:105'),  # spec 15.4.4 config-0.srl:105
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:106'),  # spec 15.4.4 config-0.srl:106
            ('rep', 14, 0, '15.4.4 config-0.srl:107'),  # spec 15.4.4 config-0.srl:107
            ('class', 'moGravityUnits_c', 1, None, '15.4.4 config-0.srl:108'),  # spec 15.4.4 config-0.srl:108
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:109'),  # spec 15.4.4 config-0.srl:109
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:110'),  # spec 15.4.4 config-0.srl:110
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:111'),  # spec 15.4.4 config-0.srl:111
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:112'),  # spec 15.4.4 config-0.srl:112
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:113'),  # spec 15.4.4 config-0.srl:113
            ('rep', 14, 0, '15.4.4 config-0.srl:114'),  # spec 15.4.4 config-0.srl:114
            ('class', 'moLinearMotorUnits_c', 1, None, '15.4.4 config-0.srl:115'),  # spec 15.4.4 config-0.srl:115
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:116'),  # spec 15.4.4 config-0.srl:116
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:117'),  # spec 15.4.4 config-0.srl:117
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:118'),  # spec 15.4.4 config-0.srl:118
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:119'),  # spec 15.4.4 config-0.srl:119
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:120'),  # spec 15.4.4 config-0.srl:120
            ('rep', 14, 0, '15.4.4 config-0.srl:121'),  # spec 15.4.4 config-0.srl:121
            ('class', 'moRotaryMotorUnits_c', 1, None, '15.4.4 config-0.srl:122'),  # spec 15.4.4 config-0.srl:122
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:123'),  # spec 15.4.4 config-0.srl:123
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:124'),  # spec 15.4.4 config-0.srl:124
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:125'),  # spec 15.4.4 config-0.srl:125
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:126'),  # spec 15.4.4 config-0.srl:126
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:127'),  # spec 15.4.4 config-0.srl:127
            ('rep', 14, 0, '15.4.4 config-0.srl:128'),  # spec 15.4.4 config-0.srl:128
            ('class', 'moPowerUnits_c', 1, None, '15.4.4 config-0.srl:129'),  # spec 15.4.4 config-0.srl:129
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:130'),  # spec 15.4.4 config-0.srl:130
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:131'),  # spec 15.4.4 config-0.srl:131
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:132'),  # spec 15.4.4 config-0.srl:132
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:133'),  # spec 15.4.4 config-0.srl:133
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:134'),  # spec 15.4.4 config-0.srl:134
            ('rep', 16, 0, '15.4.4 config-0.srl:135'),  # spec 15.4.4 config-0.srl:135
            ('class', 'moEnergyUnits_c', 1, None, '15.4.4 config-0.srl:136'),  # spec 15.4.4 config-0.srl:136
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:137'),  # spec 15.4.4 config-0.srl:137
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:138'),  # spec 15.4.4 config-0.srl:138
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:139'),  # spec 15.4.4 config-0.srl:139
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:140'),  # spec 15.4.4 config-0.srl:140
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:141'),  # spec 15.4.4 config-0.srl:141
            ('rep', 16, 0, '15.4.4 config-0.srl:142'),  # spec 15.4.4 config-0.srl:142
            ('class', 'moTimeUnits_c', 1, None, '15.4.4 config-0.srl:143'),  # spec 15.4.4 config-0.srl:143
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:144'),  # spec 15.4.4 config-0.srl:144
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:145'),  # spec 15.4.4 config-0.srl:145
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:146'),  # spec 15.4.4 config-0.srl:146
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:147'),  # spec 15.4.4 config-0.srl:147
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:148'),  # spec 15.4.4 config-0.srl:148
            ('rep', 16, 0, '15.4.4 config-0.srl:149'),  # spec 15.4.4 config-0.srl:149
            ('class', 'moFrequencyUserUnits_c', 1, None, '15.4.4 config-0.srl:150'),  # spec 15.4.4 config-0.srl:150
            ('put', 'u32', (2, 1), '15.4.4 config-0.srl:151'),  # spec 15.4.4 config-0.srl:151
            ('put', 'f64', (0.01,), '15.4.4 config-0.srl:152'),  # spec 15.4.4 config-0.srl:152
            ('put', 'u32', (10, 1), '15.4.4 config-0.srl:153'),  # spec 15.4.4 config-0.srl:153
            ('put', 'f64', (0.78539816339745,), '15.4.4 config-0.srl:154'),  # spec 15.4.4 config-0.srl:154
            ('put', 'u32', (1, 0, 1, 1), '15.4.4 config-0.srl:155'),  # spec 15.4.4 config-0.srl:155
            ('rep', 14, 0, '15.4.4 config-0.srl:156'),  # spec 15.4.4 config-0.srl:156
            ('class', 'moUnitComponent_c', 1, None, '15.4.4 config-0.srl:157'),  # spec 15.4.4 config-0.srl:157
            ('put', 'u32', (2, 0, 0), '15.4.4 config-0.srl:158'),  # spec 15.4.4 config-0.srl:158
            ('if', ('$', 'model.solid'), (  # spec 15.4.5 config-0.srl:162
                ('class', 'gcCurvatureObject_c', 1, None, '15.4.5 config-0.srl:163'),  # spec 15.4.5 config-0.srl:163
                ('put', 'f64', (1000.0,), '15.4.5 config-0.srl:164'),  # spec 15.4.5 config-0.srl:164
                ('hex', '9A99999999', '15.4.5 config-0.srl:165'),  # spec 15.4.5 config-0.srl:165
                ('put', 'u32', (4210585,), '15.4.5 config-0.srl:166'),  # spec 15.4.5 config-0.srl:166
                ('rep', 3, 0, '15.4.5 config-0.srl:167'),  # spec 15.4.5 config-0.srl:167
                ('put', 'f32', (2.25,), '15.4.5 config-0.srl:168'),  # spec 15.4.5 config-0.srl:168
                ('put', 'f64', (1.2, 1.0), '15.4.5 config-0.srl:169'),  # spec 15.4.5 config-0.srl:169
                ('put', 'u64', (('$', 'config0.curvature_time'),), '15.4.5 config-0.srl:170'),  # spec 15.4.5 config-0.srl:170
            ), (  # spec 15.4.5 config-0.srl:162
                ('put', 'u16', (0,), '15.4.5 config-0.srl:172'),  # spec 15.4.5 config-0.srl:172
            ), '15.4.5 config-0.srl:162'),  # spec 15.4.5 config-0.srl:162
            ('class', 'moTransRefPlaneData_c', 1, None, '15.4.5 config-0.srl:176'),  # spec 15.4.5 config-0.srl:176
            ('put', 'u32', (1, 1, 16221267, 6759173, 95, 0), '15.4.5 config-0.srl:177'),  # spec 15.4.5 config-0.srl:177
            ('if', ('$', 'model.solid'), (  # spec 15.4.5 config-0.srl:178
                ('put', 'u8', (1,), '15.4.5 config-0.srl:179'),  # spec 15.4.5 config-0.srl:179
                ('put', 'f64', (('$', 'model.sphere.0'), ('$', 'model.sphere.1'), ('$', 'model.sphere.2')), '15.4.5 config-0.srl:180'),  # spec 15.4.5 config-0.srl:180
                ('put', 'f64', (('$', 'model.max.0'), ('$', 'model.max.1'), ('$', 'model.max.2')), '15.4.5 config-0.srl:181'),  # spec 15.4.5 config-0.srl:181
                ('put', 'f64', (('$', 'model.min.0'), ('$', 'model.min.1'), ('$', 'model.min.2')), '15.4.5 config-0.srl:182'),  # spec 15.4.5 config-0.srl:182
                ('put', 'f64', (('$', 'model.sphere.3'),), '15.4.5 config-0.srl:183'),  # spec 15.4.5 config-0.srl:183
            ), (  # spec 15.4.5 config-0.srl:178
                ('put', 'u8', (0,), '15.4.5 config-0.srl:185'),  # spec 15.4.5 config-0.srl:185
            ), '15.4.5 config-0.srl:178'),  # spec 15.4.5 config-0.srl:178
            ('rep', 22, 0, '15.4.5 config-0.srl:187'),  # spec 15.4.5 config-0.srl:187
            ('put', 'f64', (2.0,), '15.4.5 config-0.srl:188'),  # spec 15.4.5 config-0.srl:188
            ('hex', '8F40', '15.4.5 config-0.srl:189'),  # spec 15.4.5 config-0.srl:189
            ('put', 'f64', (1e-08,), '15.4.5 config-0.srl:190'),  # spec 15.4.5 config-0.srl:190
            ('put', 'u32', (2,), '15.4.5 config-0.srl:191'),  # spec 15.4.5 config-0.srl:191
            ('rep', 2, 0, '15.4.5 config-0.srl:192'),  # spec 15.4.5 config-0.srl:192
            ('hex', 'AAAAAAAABB', '15.4.5 config-0.srl:193'),  # spec 15.4.5 config-0.srl:193
            ('put', 'u32', (12303291,), '15.4.5 config-0.srl:194'),  # spec 15.4.5 config-0.srl:194
            ('rep', 3, 0, '15.4.5 config-0.srl:195'),  # spec 15.4.5 config-0.srl:195
            ('put', 'u32', (('=', 'int($model.solid)'),), '15.4.5 config-0.srl:196'),  # spec 15.4.5 config-0.srl:196
            ('rep', 78, 0, '15.4.5 config-0.srl:197'),  # spec 15.4.5 config-0.srl:197
            ('put', 'u32', (('=', '101+len($features)'),), '15.4.5 config-0.srl:198'),  # spec 15.4.5 config-0.srl:198
            ('rep', 2, 0, '15.4.5 config-0.srl:199'),  # spec 15.4.5 config-0.srl:199
            ('class', 'gcXhatch_c', 1, None, '15.4.5 config-0.srl:200'),  # spec 15.4.5 config-0.srl:200
            ('put', 'cstr', ('ANSI31 (Iron BrickStone)',), '15.4.5 config-0.srl:201'),  # spec 15.4.5 config-0.srl:201
            ('put', 'u32', (0, 0), '15.4.5 config-0.srl:202'),  # spec 15.4.5 config-0.srl:202
            ('put', 'f64', (1.0,), '15.4.5 config-0.srl:203'),  # spec 15.4.5 config-0.srl:203
            ('put', 'u32', (0, 0, 1), '15.4.5 config-0.srl:204'),  # spec 15.4.5 config-0.srl:204
            ('put', 'i32', (-1, -1), '15.4.5 config-0.srl:205'),  # spec 15.4.5 config-0.srl:205
            ('put', 'u32', (0,), '15.4.5 config-0.srl:206'),  # spec 15.4.5 config-0.srl:206
            ('class', 'moMaterial_c', 1, None, '15.4.5 config-0.srl:207'),  # spec 15.4.5 config-0.srl:207
            ('class', 'moDensityParameter_c', 1, None, '15.4.5 config-0.srl:209'),  # spec 15.4.5 config-0.srl:209
            ('put', 'u16', (0,), '15.4.5 config-0.srl:210'),  # spec 15.4.5 config-0.srl:210
            ('put', 'u32', (0, 1073741824), '15.4.5 config-0.srl:211'),  # spec 15.4.5 config-0.srl:211
            ('put', 'i32', (-1,), '15.4.5 config-0.srl:212'),  # spec 15.4.5 config-0.srl:212
            ('put', 'u32', (0,), '15.4.5 config-0.srl:213'),  # spec 15.4.5 config-0.srl:213
            ('put', 'cstr', ('',), '15.4.5 config-0.srl:214'),  # spec 15.4.5 config-0.srl:214
            ('put', 'u16', (0,), '15.4.5 config-0.srl:215'),  # spec 15.4.5 config-0.srl:215
            ('put', 'f64', (1000.0,), '15.4.5 config-0.srl:216'),  # spec 15.4.5 config-0.srl:216
            ('put', 'u8', (0,), '15.4.5 config-0.srl:217'),  # spec 15.4.5 config-0.srl:217
            ('class', 'uoModelData_c', 1, None, '15.4.6 config-0.srl:221'),  # spec 15.4.6 config-0.srl:221
            ('rep', 34, 0, '15.4.6 config-0.srl:222'),  # spec 15.4.6 config-0.srl:222
        ), '15.4.1 config-0.srl:9'),  # spec 15.4.1 config-0.srl:9
        ('sized', 'u32', 'tail_size', (  # spec 15.4.6 config-0.srl:224
            ('rep', 6, 0, '15.4.6 config-0.srl:225'),  # spec 15.4.6 config-0.srl:225
            ('put', 'u32', (('=', '100+len($bodies)'), ('=', 'len($bodies)')), '15.4.6 config-0.srl:226'),  # spec 15.4.6 config-0.srl:226
            ('for', 'b', ('$', 'bodies'), True, (  # spec 15.4.6 config-0.srl:227
                ('class', 'moAtom_c', 1, ('$', 'b.label'), '15.4.6 config-0.srl:228'),  # spec 15.4.6 config-0.srl:228
                ('put', 'u16', (0,), '15.4.6 config-0.srl:229'),  # spec 15.4.6 config-0.srl:229
                ('put', 'u32', (1, 1073741824), '15.4.6 config-0.srl:230'),  # spec 15.4.6 config-0.srl:230
                ('put', 'i32', (-1,), '15.4.6 config-0.srl:231'),  # spec 15.4.6 config-0.srl:231
                ('put', 'u32', (0,), '15.4.6 config-0.srl:232'),  # spec 15.4.6 config-0.srl:232
                ('put', 'cstr', ('',), '15.4.6 config-0.srl:233'),  # spec 15.4.6 config-0.srl:233
                ('rep', 12, 0, '15.4.6 config-0.srl:234'),  # spec 15.4.6 config-0.srl:234
                ('put', 'u32', (('$', 'b.id'), 0), '15.4.6 config-0.srl:235'),  # spec 15.4.6 config-0.srl:235
                ('put', 'u32', (('$', 'b.feature'), ('$', 'b.feature')), '15.4.6 config-0.srl:236'),  # spec 15.4.6 config-0.srl:236
                ('rep', 12, 0, '15.4.6 config-0.srl:237'),  # spec 15.4.6 config-0.srl:237
                ('put', 'u32', (1,), '15.4.6 config-0.srl:238'),  # spec 15.4.6 config-0.srl:238
                ('put', 'i32', (-1,), '15.4.6 config-0.srl:239'),  # spec 15.4.6 config-0.srl:239
                ('put', 'u32', (('$', 'b.regen'), 1, ('$', 'b.regen'), 6), '15.4.6 config-0.srl:240'),  # spec 15.4.6 config-0.srl:240
            ), '15.4.6 config-0.srl:227'),  # spec 15.4.6 config-0.srl:227
            ('if', ('$', 'model.solid'), (  # spec 15.4.6 config-0.srl:242
                ('put', 'u32', (17000, 10001), '15.4.6 config-0.srl:243'),  # spec 15.4.6 config-0.srl:243
                ('hex', '01', '15.4.6 config-0.srl:244'),  # spec 15.4.6 config-0.srl:244
                ('rep', 2, 0, '15.4.6 config-0.srl:245'),  # spec 15.4.6 config-0.srl:245
                ('put', 'u32', (2560288, 5120), '15.4.6 config-0.srl:246'),  # spec 15.4.6 config-0.srl:246
                ('rep', 5, 0, '15.4.6 config-0.srl:247'),  # spec 15.4.6 config-0.srl:247
                ('put', 'i32', (-1,), '15.4.6 config-0.srl:248'),  # spec 15.4.6 config-0.srl:248
                ('put', 'u32', (1,), '15.4.6 config-0.srl:249'),  # spec 15.4.6 config-0.srl:249
                ('put', 'i32', (-1,), '15.4.6 config-0.srl:250'),  # spec 15.4.6 config-0.srl:250
                ('put', 'u32', (0, 0), '15.4.6 config-0.srl:251'),  # spec 15.4.6 config-0.srl:251
            ), (  # spec 15.4.6 config-0.srl:242
                ('put', 'u32', (17000, 10000), '15.4.6 config-0.srl:253'),  # spec 15.4.6 config-0.srl:253
                ('hex', '00000010', '15.4.6 config-0.srl:254'),  # spec 15.4.6 config-0.srl:254
            ), '15.4.6 config-0.srl:242'),  # spec 15.4.6 config-0.srl:242
            ('class', 'moRelMgr_c', 1, None, '15.4.7 config-0-settings.srl:4'),  # spec 15.4.7 config-0-settings.srl:4
            ('put', 'u32', (0,), '15.4.7 config-0-settings.srl:5'),  # spec 15.4.7 config-0-settings.srl:5
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:6'),  # spec 15.4.7 config-0-settings.srl:6
            ('put', 'u32', (0, 0, 1), '15.4.7 config-0-settings.srl:7'),  # spec 15.4.7 config-0-settings.srl:7
            ('put', 'i32', (-1, -65536), '15.4.7 config-0-settings.srl:8'),  # spec 15.4.7 config-0-settings.srl:8
            ('put', 'u32', (65535, 0, 1), '15.4.7 config-0-settings.srl:9'),  # spec 15.4.7 config-0-settings.srl:9
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:10'),  # spec 15.4.7 config-0-settings.srl:10
            ('put', 'f64', (0.0025,), '15.4.7 config-0-settings.srl:11'),  # spec 15.4.7 config-0-settings.srl:11
            ('put', 'u32', (4194305, 512), '15.4.7 config-0-settings.srl:12'),  # spec 15.4.7 config-0-settings.srl:12
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:13'),  # spec 15.4.7 config-0-settings.srl:13
            ('put', 'f64', (0.002,), '15.4.7 config-0-settings.srl:14'),  # spec 15.4.7 config-0-settings.srl:14
            ('put', 'u32', (65537, 1, 512, 768, 1024), '15.4.7 config-0-settings.srl:15'),  # spec 15.4.7 config-0-settings.srl:15
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:16'),  # spec 15.4.7 config-0-settings.srl:16
            ('put', 'f64', (1e-05, 1.4e-05, 2.5e-06), '15.4.7 config-0-settings.srl:17'),  # spec 15.4.7 config-0-settings.srl:17
            ('put', 'u32', (2, 3, 4), '15.4.7 config-0-settings.srl:18'),  # spec 15.4.7 config-0-settings.srl:18
            ('put', 'f64', (0.00017453292519943334, 0.0002443460952792067, 4.3633231299858336e-05), '15.4.7 config-0-settings.srl:19'),  # spec 15.4.7 config-0-settings.srl:19
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:20'),  # spec 15.4.7 config-0-settings.srl:20
            ('put', 'f64', (0.0005, 0.008726646259971667), '15.4.7 config-0-settings.srl:21'),  # spec 15.4.7 config-0-settings.srl:21
            ('put', 'u32', (1, 0, 1, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:22'),  # spec 15.4.7 config-0-settings.srl:22
            ('rep', 9, 0, '15.4.7 config-0-settings.srl:23'),  # spec 15.4.7 config-0-settings.srl:23
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:24'),  # spec 15.4.7 config-0-settings.srl:24
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:25'),  # spec 15.4.7 config-0-settings.srl:25
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:26'),  # spec 15.4.7 config-0-settings.srl:26
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:27'),  # spec 15.4.7 config-0-settings.srl:27
            ('put', 'f64', (0.008,), '15.4.7 config-0-settings.srl:28'),  # spec 15.4.7 config-0-settings.srl:28
            ('put', 'u32', (0,), '15.4.7 config-0-settings.srl:29'),  # spec 15.4.7 config-0-settings.srl:29
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:30'),  # spec 15.4.7 config-0-settings.srl:30
            ('put', 'u32', (0,), '15.4.7 config-0-settings.srl:31'),  # spec 15.4.7 config-0-settings.srl:31
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:32'),  # spec 15.4.7 config-0-settings.srl:32
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:33'),  # spec 15.4.7 config-0-settings.srl:33
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:34'),  # spec 15.4.7 config-0-settings.srl:34
            ('put', 'u32', (1, 1, 1, 1, 1, 1, 10), '15.4.7 config-0-settings.srl:35'),  # spec 15.4.7 config-0-settings.srl:35
            ('put', 'cstr', ('m',), '15.4.7 config-0-settings.srl:36'),  # spec 15.4.7 config-0-settings.srl:36
            ('put', 'cstr', ('mm',), '15.4.7 config-0-settings.srl:37'),  # spec 15.4.7 config-0-settings.srl:37
            ('put', 'cstr', ('cm',), '15.4.7 config-0-settings.srl:38'),  # spec 15.4.7 config-0-settings.srl:38
            ('put', 'cstr', ('km',), '15.4.7 config-0-settings.srl:39'),  # spec 15.4.7 config-0-settings.srl:39
            ('put', 'cstr', ('um',), '15.4.7 config-0-settings.srl:40'),  # spec 15.4.7 config-0-settings.srl:40
            ('put', 'cstr', ('µm',), '15.4.7 config-0-settings.srl:41'),  # spec 15.4.7 config-0-settings.srl:41
            ('put', 'cstr', ('nm',), '15.4.7 config-0-settings.srl:42'),  # spec 15.4.7 config-0-settings.srl:42
            ('put', 'cstr', ('s',), '15.4.7 config-0-settings.srl:43'),  # spec 15.4.7 config-0-settings.srl:43
            ('put', 'cstr', ('Hz',), '15.4.7 config-0-settings.srl:44'),  # spec 15.4.7 config-0-settings.srl:44
            ('put', 'cstr', ('Pa',), '15.4.7 config-0-settings.srl:45'),  # spec 15.4.7 config-0-settings.srl:45
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:46'),  # spec 15.4.7 config-0-settings.srl:46
            ('rep', 200, 0, '15.4.7 config-0-settings.srl:47'),  # spec 15.4.7 config-0-settings.srl:47
            ('hex', '05', '15.4.7 config-0-settings.srl:48'),  # spec 15.4.7 config-0-settings.srl:48
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:49'),  # spec 15.4.7 config-0-settings.srl:49
            ('put', 'cstr', ('Description',), '15.4.7 config-0-settings.srl:50'),  # spec 15.4.7 config-0-settings.srl:50
            ('put', 'cstr', ('High Priority',), '15.4.7 config-0-settings.srl:51'),  # spec 15.4.7 config-0-settings.srl:51
            ('put', 'cstr', ('Low Priority',), '15.4.7 config-0-settings.srl:52'),  # spec 15.4.7 config-0-settings.srl:52
            ('put', 'cstr', ('Complete',), '15.4.7 config-0-settings.srl:53'),  # spec 15.4.7 config-0-settings.srl:53
            ('put', 'cstr', ('Reminder',), '15.4.7 config-0-settings.srl:54'),  # spec 15.4.7 config-0-settings.srl:54
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:55'),  # spec 15.4.7 config-0-settings.srl:55
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:56'),  # spec 15.4.7 config-0-settings.srl:56
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:57'),  # spec 15.4.7 config-0-settings.srl:57
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:58'),  # spec 15.4.7 config-0-settings.srl:58
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:59'),  # spec 15.4.7 config-0-settings.srl:59
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:60'),  # spec 15.4.7 config-0-settings.srl:60
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:61'),  # spec 15.4.7 config-0-settings.srl:61
            ('put', 'f64', (0.001016, 0.003302, 0.00635, 0.001, 0.001, 0.005, 0.01, 0.003175), '15.4.7 config-0-settings.srl:62'),  # spec 15.4.7 config-0-settings.srl:62
            ('put', 'f64', (0.001524, 0.00635, -25.0), '15.4.7 config-0-settings.srl:63'),  # spec 15.4.7 config-0-settings.srl:63
            ('put', 'u32', (2, 0, 1, 20, 1), '15.4.7 config-0-settings.srl:64'),  # spec 15.4.7 config-0-settings.srl:64
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:65'),  # spec 15.4.7 config-0-settings.srl:65
            ('put', 'f64', (0.01, 0.006, 0.26179938779915), '15.4.7 config-0-settings.srl:66'),  # spec 15.4.7 config-0-settings.srl:66
            ('put', 'u32', (8368, 1), '15.4.7 config-0-settings.srl:67'),  # spec 15.4.7 config-0-settings.srl:67
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:68'),  # spec 15.4.7 config-0-settings.srl:68
            ('put', 'u32', (0, 1, 1, 1, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:69'),  # spec 15.4.7 config-0-settings.srl:69
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:70'),  # spec 15.4.7 config-0-settings.srl:70
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:71'),  # spec 15.4.7 config-0-settings.srl:71
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:72'),  # spec 15.4.7 config-0-settings.srl:72
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:73'),  # spec 15.4.7 config-0-settings.srl:73
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:74'),  # spec 15.4.7 config-0-settings.srl:74
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:75'),  # spec 15.4.7 config-0-settings.srl:75
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:76'),  # spec 15.4.7 config-0-settings.srl:76
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:77'),  # spec 15.4.7 config-0-settings.srl:77
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:78'),  # spec 15.4.7 config-0-settings.srl:78
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:79'),  # spec 15.4.7 config-0-settings.srl:79
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:80'),  # spec 15.4.7 config-0-settings.srl:80
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:81'),  # spec 15.4.7 config-0-settings.srl:81
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:82'),  # spec 15.4.7 config-0-settings.srl:82
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:83'),  # spec 15.4.7 config-0-settings.srl:83
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:84'),  # spec 15.4.7 config-0-settings.srl:84
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:85'),  # spec 15.4.7 config-0-settings.srl:85
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:86'),  # spec 15.4.7 config-0-settings.srl:86
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:87'),  # spec 15.4.7 config-0-settings.srl:87
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:88'),  # spec 15.4.7 config-0-settings.srl:88
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:89'),  # spec 15.4.7 config-0-settings.srl:89
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:90'),  # spec 15.4.7 config-0-settings.srl:90
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:91'),  # spec 15.4.7 config-0-settings.srl:91
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:92'),  # spec 15.4.7 config-0-settings.srl:92
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:93'),  # spec 15.4.7 config-0-settings.srl:93
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:94'),  # spec 15.4.7 config-0-settings.srl:94
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:95'),  # spec 15.4.7 config-0-settings.srl:95
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:96'),  # spec 15.4.7 config-0-settings.srl:96
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:97'),  # spec 15.4.7 config-0-settings.srl:97
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:98'),  # spec 15.4.7 config-0-settings.srl:98
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:99'),  # spec 15.4.7 config-0-settings.srl:99
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:100'),  # spec 15.4.7 config-0-settings.srl:100
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:101'),  # spec 15.4.7 config-0-settings.srl:101
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:102'),  # spec 15.4.7 config-0-settings.srl:102
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:103'),  # spec 15.4.7 config-0-settings.srl:103
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:104'),  # spec 15.4.7 config-0-settings.srl:104
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:105'),  # spec 15.4.7 config-0-settings.srl:105
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:106'),  # spec 15.4.7 config-0-settings.srl:106
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:107'),  # spec 15.4.7 config-0-settings.srl:107
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:108'),  # spec 15.4.7 config-0-settings.srl:108
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:109'),  # spec 15.4.7 config-0-settings.srl:109
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:110'),  # spec 15.4.7 config-0-settings.srl:110
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:111'),  # spec 15.4.7 config-0-settings.srl:111
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:112'),  # spec 15.4.7 config-0-settings.srl:112
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:113'),  # spec 15.4.7 config-0-settings.srl:113
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:114'),  # spec 15.4.7 config-0-settings.srl:114
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:115'),  # spec 15.4.7 config-0-settings.srl:115
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:116'),  # spec 15.4.7 config-0-settings.srl:116
            ('put', 'u32', (2, 0, 1, 1, 1), '15.4.7 config-0-settings.srl:117'),  # spec 15.4.7 config-0-settings.srl:117
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:118'),  # spec 15.4.7 config-0-settings.srl:118
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:119'),  # spec 15.4.7 config-0-settings.srl:119
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:120'),  # spec 15.4.7 config-0-settings.srl:120
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:121'),  # spec 15.4.7 config-0-settings.srl:121
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:122'),  # spec 15.4.7 config-0-settings.srl:122
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:123'),  # spec 15.4.7 config-0-settings.srl:123
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:124'),  # spec 15.4.7 config-0-settings.srl:124
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:125'),  # spec 15.4.7 config-0-settings.srl:125
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:126'),  # spec 15.4.7 config-0-settings.srl:126
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:127'),  # spec 15.4.7 config-0-settings.srl:127
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:128'),  # spec 15.4.7 config-0-settings.srl:128
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:129'),  # spec 15.4.7 config-0-settings.srl:129
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:130'),  # spec 15.4.7 config-0-settings.srl:130
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:131'),  # spec 15.4.7 config-0-settings.srl:131
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:132'),  # spec 15.4.7 config-0-settings.srl:132
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:133'),  # spec 15.4.7 config-0-settings.srl:133
            ('put', 'u32', (2, 2, 1), '15.4.7 config-0-settings.srl:134'),  # spec 15.4.7 config-0-settings.srl:134
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:135'),  # spec 15.4.7 config-0-settings.srl:135
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:136'),  # spec 15.4.7 config-0-settings.srl:136
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:137'),  # spec 15.4.7 config-0-settings.srl:137
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:138'),  # spec 15.4.7 config-0-settings.srl:138
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:139'),  # spec 15.4.7 config-0-settings.srl:139
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:140'),  # spec 15.4.7 config-0-settings.srl:140
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:141'),  # spec 15.4.7 config-0-settings.srl:141
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:142'),  # spec 15.4.7 config-0-settings.srl:142
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:143'),  # spec 15.4.7 config-0-settings.srl:143
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:144'),  # spec 15.4.7 config-0-settings.srl:144
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:145'),  # spec 15.4.7 config-0-settings.srl:145
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:146'),  # spec 15.4.7 config-0-settings.srl:146
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:147'),  # spec 15.4.7 config-0-settings.srl:147
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:148'),  # spec 15.4.7 config-0-settings.srl:148
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:149'),  # spec 15.4.7 config-0-settings.srl:149
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:150'),  # spec 15.4.7 config-0-settings.srl:150
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:151'),  # spec 15.4.7 config-0-settings.srl:151
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:152'),  # spec 15.4.7 config-0-settings.srl:152
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:153'),  # spec 15.4.7 config-0-settings.srl:153
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:154'),  # spec 15.4.7 config-0-settings.srl:154
            ('put', 'u32', (1, 0, 0, 322, 1, 1, 1), '15.4.7 config-0-settings.srl:155'),  # spec 15.4.7 config-0-settings.srl:155
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:156'),  # spec 15.4.7 config-0-settings.srl:156
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:157'),  # spec 15.4.7 config-0-settings.srl:157
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:158'),  # spec 15.4.7 config-0-settings.srl:158
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:159'),  # spec 15.4.7 config-0-settings.srl:159
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:160'),  # spec 15.4.7 config-0-settings.srl:160
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:161'),  # spec 15.4.7 config-0-settings.srl:161
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:162'),  # spec 15.4.7 config-0-settings.srl:162
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:163'),  # spec 15.4.7 config-0-settings.srl:163
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:164'),  # spec 15.4.7 config-0-settings.srl:164
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:165'),  # spec 15.4.7 config-0-settings.srl:165
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:166'),  # spec 15.4.7 config-0-settings.srl:166
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:167'),  # spec 15.4.7 config-0-settings.srl:167
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:168'),  # spec 15.4.7 config-0-settings.srl:168
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:169'),  # spec 15.4.7 config-0-settings.srl:169
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:170'),  # spec 15.4.7 config-0-settings.srl:170
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:171'),  # spec 15.4.7 config-0-settings.srl:171
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:172'),  # spec 15.4.7 config-0-settings.srl:172
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:173'),  # spec 15.4.7 config-0-settings.srl:173
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:174'),  # spec 15.4.7 config-0-settings.srl:174
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:175'),  # spec 15.4.7 config-0-settings.srl:175
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:176'),  # spec 15.4.7 config-0-settings.srl:176
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:177'),  # spec 15.4.7 config-0-settings.srl:177
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:178'),  # spec 15.4.7 config-0-settings.srl:178
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:179'),  # spec 15.4.7 config-0-settings.srl:179
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:180'),  # spec 15.4.7 config-0-settings.srl:180
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:181'),  # spec 15.4.7 config-0-settings.srl:181
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:182'),  # spec 15.4.7 config-0-settings.srl:182
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:183'),  # spec 15.4.7 config-0-settings.srl:183
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:184'),  # spec 15.4.7 config-0-settings.srl:184
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:185'),  # spec 15.4.7 config-0-settings.srl:185
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:186'),  # spec 15.4.7 config-0-settings.srl:186
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:187'),  # spec 15.4.7 config-0-settings.srl:187
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:188'),  # spec 15.4.7 config-0-settings.srl:188
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:189'),  # spec 15.4.7 config-0-settings.srl:189
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:190'),  # spec 15.4.7 config-0-settings.srl:190
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:191'),  # spec 15.4.7 config-0-settings.srl:191
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:192'),  # spec 15.4.7 config-0-settings.srl:192
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:193'),  # spec 15.4.7 config-0-settings.srl:193
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:194'),  # spec 15.4.7 config-0-settings.srl:194
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:195'),  # spec 15.4.7 config-0-settings.srl:195
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:196'),  # spec 15.4.7 config-0-settings.srl:196
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:197'),  # spec 15.4.7 config-0-settings.srl:197
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:198'),  # spec 15.4.7 config-0-settings.srl:198
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:199'),  # spec 15.4.7 config-0-settings.srl:199
            ('put', 'u32', (1, 0, 0, 1, 1, 1), '15.4.7 config-0-settings.srl:200'),  # spec 15.4.7 config-0-settings.srl:200
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:201'),  # spec 15.4.7 config-0-settings.srl:201
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:202'),  # spec 15.4.7 config-0-settings.srl:202
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:203'),  # spec 15.4.7 config-0-settings.srl:203
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:204'),  # spec 15.4.7 config-0-settings.srl:204
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:205'),  # spec 15.4.7 config-0-settings.srl:205
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:206'),  # spec 15.4.7 config-0-settings.srl:206
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:207'),  # spec 15.4.7 config-0-settings.srl:207
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:208'),  # spec 15.4.7 config-0-settings.srl:208
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:209'),  # spec 15.4.7 config-0-settings.srl:209
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:210'),  # spec 15.4.7 config-0-settings.srl:210
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:211'),  # spec 15.4.7 config-0-settings.srl:211
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:212'),  # spec 15.4.7 config-0-settings.srl:212
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:213'),  # spec 15.4.7 config-0-settings.srl:213
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:214'),  # spec 15.4.7 config-0-settings.srl:214
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:215'),  # spec 15.4.7 config-0-settings.srl:215
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:216'),  # spec 15.4.7 config-0-settings.srl:216
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:217'),  # spec 15.4.7 config-0-settings.srl:217
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:218'),  # spec 15.4.7 config-0-settings.srl:218
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:219'),  # spec 15.4.7 config-0-settings.srl:219
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:220'),  # spec 15.4.7 config-0-settings.srl:220
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:221'),  # spec 15.4.7 config-0-settings.srl:221
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:222'),  # spec 15.4.7 config-0-settings.srl:222
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:223'),  # spec 15.4.7 config-0-settings.srl:223
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:224'),  # spec 15.4.7 config-0-settings.srl:224
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:225'),  # spec 15.4.7 config-0-settings.srl:225
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:226'),  # spec 15.4.7 config-0-settings.srl:226
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:227'),  # spec 15.4.7 config-0-settings.srl:227
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:228'),  # spec 15.4.7 config-0-settings.srl:228
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:229'),  # spec 15.4.7 config-0-settings.srl:229
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:230'),  # spec 15.4.7 config-0-settings.srl:230
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:231'),  # spec 15.4.7 config-0-settings.srl:231
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:232'),  # spec 15.4.7 config-0-settings.srl:232
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:233'),  # spec 15.4.7 config-0-settings.srl:233
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:234'),  # spec 15.4.7 config-0-settings.srl:234
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:235'),  # spec 15.4.7 config-0-settings.srl:235
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:236'),  # spec 15.4.7 config-0-settings.srl:236
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:237'),  # spec 15.4.7 config-0-settings.srl:237
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:238'),  # spec 15.4.7 config-0-settings.srl:238
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:239'),  # spec 15.4.7 config-0-settings.srl:239
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:240'),  # spec 15.4.7 config-0-settings.srl:240
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:241'),  # spec 15.4.7 config-0-settings.srl:241
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:242'),  # spec 15.4.7 config-0-settings.srl:242
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:243'),  # spec 15.4.7 config-0-settings.srl:243
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:244'),  # spec 15.4.7 config-0-settings.srl:244
            ('put', 'u32', (1, 0, 0, 2, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:245'),  # spec 15.4.7 config-0-settings.srl:245
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:246'),  # spec 15.4.7 config-0-settings.srl:246
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:247'),  # spec 15.4.7 config-0-settings.srl:247
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:248'),  # spec 15.4.7 config-0-settings.srl:248
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:249'),  # spec 15.4.7 config-0-settings.srl:249
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:250'),  # spec 15.4.7 config-0-settings.srl:250
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:251'),  # spec 15.4.7 config-0-settings.srl:251
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:252'),  # spec 15.4.7 config-0-settings.srl:252
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:253'),  # spec 15.4.7 config-0-settings.srl:253
            ('put', 'u32', (131071,), '15.4.7 config-0-settings.srl:254'),  # spec 15.4.7 config-0-settings.srl:254
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:255'),  # spec 15.4.7 config-0-settings.srl:255
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:256'),  # spec 15.4.7 config-0-settings.srl:256
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:257'),  # spec 15.4.7 config-0-settings.srl:257
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:258'),  # spec 15.4.7 config-0-settings.srl:258
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:259'),  # spec 15.4.7 config-0-settings.srl:259
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:260'),  # spec 15.4.7 config-0-settings.srl:260
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:261'),  # spec 15.4.7 config-0-settings.srl:261
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:262'),  # spec 15.4.7 config-0-settings.srl:262
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:263'),  # spec 15.4.7 config-0-settings.srl:263
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:264'),  # spec 15.4.7 config-0-settings.srl:264
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:265'),  # spec 15.4.7 config-0-settings.srl:265
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:266'),  # spec 15.4.7 config-0-settings.srl:266
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:267'),  # spec 15.4.7 config-0-settings.srl:267
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:268'),  # spec 15.4.7 config-0-settings.srl:268
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:269'),  # spec 15.4.7 config-0-settings.srl:269
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:270'),  # spec 15.4.7 config-0-settings.srl:270
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:271'),  # spec 15.4.7 config-0-settings.srl:271
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:272'),  # spec 15.4.7 config-0-settings.srl:272
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:273'),  # spec 15.4.7 config-0-settings.srl:273
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:274'),  # spec 15.4.7 config-0-settings.srl:274
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:275'),  # spec 15.4.7 config-0-settings.srl:275
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:276'),  # spec 15.4.7 config-0-settings.srl:276
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:277'),  # spec 15.4.7 config-0-settings.srl:277
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:278'),  # spec 15.4.7 config-0-settings.srl:278
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:279'),  # spec 15.4.7 config-0-settings.srl:279
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:280'),  # spec 15.4.7 config-0-settings.srl:280
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:281'),  # spec 15.4.7 config-0-settings.srl:281
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:282'),  # spec 15.4.7 config-0-settings.srl:282
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:283'),  # spec 15.4.7 config-0-settings.srl:283
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:284'),  # spec 15.4.7 config-0-settings.srl:284
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:285'),  # spec 15.4.7 config-0-settings.srl:285
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:286'),  # spec 15.4.7 config-0-settings.srl:286
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:287'),  # spec 15.4.7 config-0-settings.srl:287
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:288'),  # spec 15.4.7 config-0-settings.srl:288
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:289'),  # spec 15.4.7 config-0-settings.srl:289
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:290'),  # spec 15.4.7 config-0-settings.srl:290
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:291'),  # spec 15.4.7 config-0-settings.srl:291
            ('put', 'u32', (1, 1, 1), '15.4.7 config-0-settings.srl:292'),  # spec 15.4.7 config-0-settings.srl:292
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:293'),  # spec 15.4.7 config-0-settings.srl:293
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:294'),  # spec 15.4.7 config-0-settings.srl:294
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:295'),  # spec 15.4.7 config-0-settings.srl:295
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:296'),  # spec 15.4.7 config-0-settings.srl:296
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:297'),  # spec 15.4.7 config-0-settings.srl:297
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:298'),  # spec 15.4.7 config-0-settings.srl:298
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:299'),  # spec 15.4.7 config-0-settings.srl:299
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:300'),  # spec 15.4.7 config-0-settings.srl:300
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:301'),  # spec 15.4.7 config-0-settings.srl:301
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:302'),  # spec 15.4.7 config-0-settings.srl:302
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:303'),  # spec 15.4.7 config-0-settings.srl:303
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:304'),  # spec 15.4.7 config-0-settings.srl:304
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:305'),  # spec 15.4.7 config-0-settings.srl:305
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:306'),  # spec 15.4.7 config-0-settings.srl:306
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:307'),  # spec 15.4.7 config-0-settings.srl:307
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:308'),  # spec 15.4.7 config-0-settings.srl:308
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:309'),  # spec 15.4.7 config-0-settings.srl:309
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:310'),  # spec 15.4.7 config-0-settings.srl:310
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:311'),  # spec 15.4.7 config-0-settings.srl:311
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:312'),  # spec 15.4.7 config-0-settings.srl:312
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:313'),  # spec 15.4.7 config-0-settings.srl:313
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:314'),  # spec 15.4.7 config-0-settings.srl:314
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:315'),  # spec 15.4.7 config-0-settings.srl:315
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:316'),  # spec 15.4.7 config-0-settings.srl:316
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:317'),  # spec 15.4.7 config-0-settings.srl:317
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:318'),  # spec 15.4.7 config-0-settings.srl:318
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:319'),  # spec 15.4.7 config-0-settings.srl:319
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:320'),  # spec 15.4.7 config-0-settings.srl:320
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:321'),  # spec 15.4.7 config-0-settings.srl:321
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:322'),  # spec 15.4.7 config-0-settings.srl:322
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:323'),  # spec 15.4.7 config-0-settings.srl:323
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:324'),  # spec 15.4.7 config-0-settings.srl:324
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:325'),  # spec 15.4.7 config-0-settings.srl:325
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:326'),  # spec 15.4.7 config-0-settings.srl:326
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:327'),  # spec 15.4.7 config-0-settings.srl:327
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:328'),  # spec 15.4.7 config-0-settings.srl:328
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:329'),  # spec 15.4.7 config-0-settings.srl:329
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:330'),  # spec 15.4.7 config-0-settings.srl:330
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:331'),  # spec 15.4.7 config-0-settings.srl:331
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:332'),  # spec 15.4.7 config-0-settings.srl:332
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:333'),  # spec 15.4.7 config-0-settings.srl:333
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:334'),  # spec 15.4.7 config-0-settings.srl:334
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:335'),  # spec 15.4.7 config-0-settings.srl:335
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:336'),  # spec 15.4.7 config-0-settings.srl:336
            ('put', 'u32', (1, 0, 0, 1, 1), '15.4.7 config-0-settings.srl:337'),  # spec 15.4.7 config-0-settings.srl:337
            ('put', 'f64', (0.0015875,), '15.4.7 config-0-settings.srl:338'),  # spec 15.4.7 config-0-settings.srl:338
            ('put', 'u32', (1, 1, 2), '15.4.7 config-0-settings.srl:339'),  # spec 15.4.7 config-0-settings.srl:339
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:340'),  # spec 15.4.7 config-0-settings.srl:340
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:341'),  # spec 15.4.7 config-0-settings.srl:341
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:342'),  # spec 15.4.7 config-0-settings.srl:342
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:343'),  # spec 15.4.7 config-0-settings.srl:343
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:344'),  # spec 15.4.7 config-0-settings.srl:344
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:345'),  # spec 15.4.7 config-0-settings.srl:345
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:346'),  # spec 15.4.7 config-0-settings.srl:346
            ('put', 'u32', (1, 3, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:347'),  # spec 15.4.7 config-0-settings.srl:347
            ('put', 'u32', (131071,), '15.4.7 config-0-settings.srl:348'),  # spec 15.4.7 config-0-settings.srl:348
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:349'),  # spec 15.4.7 config-0-settings.srl:349
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:350'),  # spec 15.4.7 config-0-settings.srl:350
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:351'),  # spec 15.4.7 config-0-settings.srl:351
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:352'),  # spec 15.4.7 config-0-settings.srl:352
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:353'),  # spec 15.4.7 config-0-settings.srl:353
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:354'),  # spec 15.4.7 config-0-settings.srl:354
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:355'),  # spec 15.4.7 config-0-settings.srl:355
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:356'),  # spec 15.4.7 config-0-settings.srl:356
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:357'),  # spec 15.4.7 config-0-settings.srl:357
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:358'),  # spec 15.4.7 config-0-settings.srl:358
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:359'),  # spec 15.4.7 config-0-settings.srl:359
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:360'),  # spec 15.4.7 config-0-settings.srl:360
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:361'),  # spec 15.4.7 config-0-settings.srl:361
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:362'),  # spec 15.4.7 config-0-settings.srl:362
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:363'),  # spec 15.4.7 config-0-settings.srl:363
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:364'),  # spec 15.4.7 config-0-settings.srl:364
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:365'),  # spec 15.4.7 config-0-settings.srl:365
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:366'),  # spec 15.4.7 config-0-settings.srl:366
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:367'),  # spec 15.4.7 config-0-settings.srl:367
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:368'),  # spec 15.4.7 config-0-settings.srl:368
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:369'),  # spec 15.4.7 config-0-settings.srl:369
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:370'),  # spec 15.4.7 config-0-settings.srl:370
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:371'),  # spec 15.4.7 config-0-settings.srl:371
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:372'),  # spec 15.4.7 config-0-settings.srl:372
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:373'),  # spec 15.4.7 config-0-settings.srl:373
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:374'),  # spec 15.4.7 config-0-settings.srl:374
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:375'),  # spec 15.4.7 config-0-settings.srl:375
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:376'),  # spec 15.4.7 config-0-settings.srl:376
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:377'),  # spec 15.4.7 config-0-settings.srl:377
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:378'),  # spec 15.4.7 config-0-settings.srl:378
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:379'),  # spec 15.4.7 config-0-settings.srl:379
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:380'),  # spec 15.4.7 config-0-settings.srl:380
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:381'),  # spec 15.4.7 config-0-settings.srl:381
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:382'),  # spec 15.4.7 config-0-settings.srl:382
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:383'),  # spec 15.4.7 config-0-settings.srl:383
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:384'),  # spec 15.4.7 config-0-settings.srl:384
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:385'),  # spec 15.4.7 config-0-settings.srl:385
            ('put', 'u32', (1, 2, 2), '15.4.7 config-0-settings.srl:386'),  # spec 15.4.7 config-0-settings.srl:386
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:387'),  # spec 15.4.7 config-0-settings.srl:387
            ('put', 'u32', (1, 1, 1), '15.4.7 config-0-settings.srl:388'),  # spec 15.4.7 config-0-settings.srl:388
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:389'),  # spec 15.4.7 config-0-settings.srl:389
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:390'),  # spec 15.4.7 config-0-settings.srl:390
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:391'),  # spec 15.4.7 config-0-settings.srl:391
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:392'),  # spec 15.4.7 config-0-settings.srl:392
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:393'),  # spec 15.4.7 config-0-settings.srl:393
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:394'),  # spec 15.4.7 config-0-settings.srl:394
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:395'),  # spec 15.4.7 config-0-settings.srl:395
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:396'),  # spec 15.4.7 config-0-settings.srl:396
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:397'),  # spec 15.4.7 config-0-settings.srl:397
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:398'),  # spec 15.4.7 config-0-settings.srl:398
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:399'),  # spec 15.4.7 config-0-settings.srl:399
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:400'),  # spec 15.4.7 config-0-settings.srl:400
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:401'),  # spec 15.4.7 config-0-settings.srl:401
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:402'),  # spec 15.4.7 config-0-settings.srl:402
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:403'),  # spec 15.4.7 config-0-settings.srl:403
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:404'),  # spec 15.4.7 config-0-settings.srl:404
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:405'),  # spec 15.4.7 config-0-settings.srl:405
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:406'),  # spec 15.4.7 config-0-settings.srl:406
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:407'),  # spec 15.4.7 config-0-settings.srl:407
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:408'),  # spec 15.4.7 config-0-settings.srl:408
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:409'),  # spec 15.4.7 config-0-settings.srl:409
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:410'),  # spec 15.4.7 config-0-settings.srl:410
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:411'),  # spec 15.4.7 config-0-settings.srl:411
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:412'),  # spec 15.4.7 config-0-settings.srl:412
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:413'),  # spec 15.4.7 config-0-settings.srl:413
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:414'),  # spec 15.4.7 config-0-settings.srl:414
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:415'),  # spec 15.4.7 config-0-settings.srl:415
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:416'),  # spec 15.4.7 config-0-settings.srl:416
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:417'),  # spec 15.4.7 config-0-settings.srl:417
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:418'),  # spec 15.4.7 config-0-settings.srl:418
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:419'),  # spec 15.4.7 config-0-settings.srl:419
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:420'),  # spec 15.4.7 config-0-settings.srl:420
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:421'),  # spec 15.4.7 config-0-settings.srl:421
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:422'),  # spec 15.4.7 config-0-settings.srl:422
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:423'),  # spec 15.4.7 config-0-settings.srl:423
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:424'),  # spec 15.4.7 config-0-settings.srl:424
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:425'),  # spec 15.4.7 config-0-settings.srl:425
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:426'),  # spec 15.4.7 config-0-settings.srl:426
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:427'),  # spec 15.4.7 config-0-settings.srl:427
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:428'),  # spec 15.4.7 config-0-settings.srl:428
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:429'),  # spec 15.4.7 config-0-settings.srl:429
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:430'),  # spec 15.4.7 config-0-settings.srl:430
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:431'),  # spec 15.4.7 config-0-settings.srl:431
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:432'),  # spec 15.4.7 config-0-settings.srl:432
            ('put', 'u32', (1, 0, 0, 1, 0, 1, 1, 1), '15.4.7 config-0-settings.srl:433'),  # spec 15.4.7 config-0-settings.srl:433
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:434'),  # spec 15.4.7 config-0-settings.srl:434
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:435'),  # spec 15.4.7 config-0-settings.srl:435
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:436'),  # spec 15.4.7 config-0-settings.srl:436
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:437'),  # spec 15.4.7 config-0-settings.srl:437
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:438'),  # spec 15.4.7 config-0-settings.srl:438
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:439'),  # spec 15.4.7 config-0-settings.srl:439
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:440'),  # spec 15.4.7 config-0-settings.srl:440
            ('put', 'u32', (1, 0, 1, 0, 2, 2, 2, 2), '15.4.7 config-0-settings.srl:441'),  # spec 15.4.7 config-0-settings.srl:441
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:442'),  # spec 15.4.7 config-0-settings.srl:442
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:443'),  # spec 15.4.7 config-0-settings.srl:443
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:444'),  # spec 15.4.7 config-0-settings.srl:444
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:445'),  # spec 15.4.7 config-0-settings.srl:445
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:446'),  # spec 15.4.7 config-0-settings.srl:446
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:447'),  # spec 15.4.7 config-0-settings.srl:447
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:448'),  # spec 15.4.7 config-0-settings.srl:448
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:449'),  # spec 15.4.7 config-0-settings.srl:449
            ('put', 'u32', (2, 2, 1), '15.4.7 config-0-settings.srl:450'),  # spec 15.4.7 config-0-settings.srl:450
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:451'),  # spec 15.4.7 config-0-settings.srl:451
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:452'),  # spec 15.4.7 config-0-settings.srl:452
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:453'),  # spec 15.4.7 config-0-settings.srl:453
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:454'),  # spec 15.4.7 config-0-settings.srl:454
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:455'),  # spec 15.4.7 config-0-settings.srl:455
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:456'),  # spec 15.4.7 config-0-settings.srl:456
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:457'),  # spec 15.4.7 config-0-settings.srl:457
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:458'),  # spec 15.4.7 config-0-settings.srl:458
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:459'),  # spec 15.4.7 config-0-settings.srl:459
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:460'),  # spec 15.4.7 config-0-settings.srl:460
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:461'),  # spec 15.4.7 config-0-settings.srl:461
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:462'),  # spec 15.4.7 config-0-settings.srl:462
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:463'),  # spec 15.4.7 config-0-settings.srl:463
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:464'),  # spec 15.4.7 config-0-settings.srl:464
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:465'),  # spec 15.4.7 config-0-settings.srl:465
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:466'),  # spec 15.4.7 config-0-settings.srl:466
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:467'),  # spec 15.4.7 config-0-settings.srl:467
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:468'),  # spec 15.4.7 config-0-settings.srl:468
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:469'),  # spec 15.4.7 config-0-settings.srl:469
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:470'),  # spec 15.4.7 config-0-settings.srl:470
            ('put', 'u32', (1, 0, 0, 1, 21), '15.4.7 config-0-settings.srl:471'),  # spec 15.4.7 config-0-settings.srl:471
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:472'),  # spec 15.4.7 config-0-settings.srl:472
            ('put', 'u32', (1, 1, 1), '15.4.7 config-0-settings.srl:473'),  # spec 15.4.7 config-0-settings.srl:473
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:474'),  # spec 15.4.7 config-0-settings.srl:474
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:475'),  # spec 15.4.7 config-0-settings.srl:475
            ('put', 'f64', (1.0, 0.0127), '15.4.7 config-0-settings.srl:476'),  # spec 15.4.7 config-0-settings.srl:476
            ('put', 'u32', (1, 0), '15.4.7 config-0-settings.srl:477'),  # spec 15.4.7 config-0-settings.srl:477
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:478'),  # spec 15.4.7 config-0-settings.srl:478
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:479'),  # spec 15.4.7 config-0-settings.srl:479
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:480'),  # spec 15.4.7 config-0-settings.srl:480
            ('put', 'u32', (1, 0, 1, 0, 2, 3, 2, 3), '15.4.7 config-0-settings.srl:481'),  # spec 15.4.7 config-0-settings.srl:481
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:482'),  # spec 15.4.7 config-0-settings.srl:482
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:483'),  # spec 15.4.7 config-0-settings.srl:483
            ('put', 'u32', (192, 2, 1), '15.4.7 config-0-settings.srl:484'),  # spec 15.4.7 config-0-settings.srl:484
            ('put', 'f64', (0.254,), '15.4.7 config-0-settings.srl:485'),  # spec 15.4.7 config-0-settings.srl:485
            ('put', 'u32', (4, 1), '15.4.7 config-0-settings.srl:486'),  # spec 15.4.7 config-0-settings.srl:486
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:487'),  # spec 15.4.7 config-0-settings.srl:487
            ('put', 'u32', (0, 0, 1, 1), '15.4.7 config-0-settings.srl:488'),  # spec 15.4.7 config-0-settings.srl:488
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:489'),  # spec 15.4.7 config-0-settings.srl:489
            ('class', 'moLengthUserUnits_c', 1, None, '15.4.7 config-0-settings.srl:490'),  # spec 15.4.7 config-0-settings.srl:490
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:491'),  # spec 15.4.7 config-0-settings.srl:491
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:492'),  # spec 15.4.7 config-0-settings.srl:492
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:493'),  # spec 15.4.7 config-0-settings.srl:493
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:494'),  # spec 15.4.7 config-0-settings.srl:494
            ('put', 'u32', (2, 0, 1, 1), '15.4.7 config-0-settings.srl:495'),  # spec 15.4.7 config-0-settings.srl:495
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:496'),  # spec 15.4.7 config-0-settings.srl:496
            ('put', 'u32', (3, 2, 1), '15.4.7 config-0-settings.srl:497'),  # spec 15.4.7 config-0-settings.srl:497
            ('put', 'f64', (0.01,), '15.4.7 config-0-settings.srl:498'),  # spec 15.4.7 config-0-settings.srl:498
            ('put', 'u32', (10, 1), '15.4.7 config-0-settings.srl:499'),  # spec 15.4.7 config-0-settings.srl:499
            ('put', 'f64', (0.78539816339745,), '15.4.7 config-0-settings.srl:500'),  # spec 15.4.7 config-0-settings.srl:500
            ('put', 'u32', (1, 0, 1, 1), '15.4.7 config-0-settings.srl:501'),  # spec 15.4.7 config-0-settings.srl:501
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:502'),  # spec 15.4.7 config-0-settings.srl:502
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:503'),  # spec 15.4.7 config-0-settings.srl:503
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:504'),  # spec 15.4.7 config-0-settings.srl:504
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:505'),  # spec 15.4.7 config-0-settings.srl:505
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:506'),  # spec 15.4.7 config-0-settings.srl:506
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:507'),  # spec 15.4.7 config-0-settings.srl:507
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:508'),  # spec 15.4.7 config-0-settings.srl:508
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:509'),  # spec 15.4.7 config-0-settings.srl:509
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:510'),  # spec 15.4.7 config-0-settings.srl:510
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:511'),  # spec 15.4.7 config-0-settings.srl:511
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:512'),  # spec 15.4.7 config-0-settings.srl:512
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:513'),  # spec 15.4.7 config-0-settings.srl:513
            ('put', 'cstr', ('CONTINUOUS',), '15.4.7 config-0-settings.srl:514'),  # spec 15.4.7 config-0-settings.srl:514
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:515'),  # spec 15.4.7 config-0-settings.srl:515
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:516'),  # spec 15.4.7 config-0-settings.srl:516
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:517'),  # spec 15.4.7 config-0-settings.srl:517
            ('put', 'u32', (1, 0, 0, 1), '15.4.7 config-0-settings.srl:518'),  # spec 15.4.7 config-0-settings.srl:518
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:519'),  # spec 15.4.7 config-0-settings.srl:519
            ('put', 'u32', (0, 1, 3, 1, 0, 0, 1, 1), '15.4.7 config-0-settings.srl:520'),  # spec 15.4.7 config-0-settings.srl:520
            ('put', 'u32', (0, 1, 1), '15.4.7 config-0-settings.srl:521'),  # spec 15.4.7 config-0-settings.srl:521
            ('put', 'f64', (0.00625,), '15.4.7 config-0-settings.srl:522'),  # spec 15.4.7 config-0-settings.srl:522
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:523'),  # spec 15.4.7 config-0-settings.srl:523
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:524'),  # spec 15.4.7 config-0-settings.srl:524
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:525'),  # spec 15.4.7 config-0-settings.srl:525
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:526'),  # spec 15.4.7 config-0-settings.srl:526
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:527'),  # spec 15.4.7 config-0-settings.srl:527
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:528'),  # spec 15.4.7 config-0-settings.srl:528
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:529'),  # spec 15.4.7 config-0-settings.srl:529
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:530'),  # spec 15.4.7 config-0-settings.srl:530
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:531'),  # spec 15.4.7 config-0-settings.srl:531
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:532'),  # spec 15.4.7 config-0-settings.srl:532
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:533'),  # spec 15.4.7 config-0-settings.srl:533
            ('put', 'u32', (400, 0, 2, 2, 1, 1, 1, 2), '15.4.7 config-0-settings.srl:534'),  # spec 15.4.7 config-0-settings.srl:534
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:535'),  # spec 15.4.7 config-0-settings.srl:535
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:536'),  # spec 15.4.7 config-0-settings.srl:536
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:537'),  # spec 15.4.7 config-0-settings.srl:537
            ('put', 'f64', (0.01016, 0.01016), '15.4.7 config-0-settings.srl:538'),  # spec 15.4.7 config-0-settings.srl:538
            ('put', 'u32', (0, 1), '15.4.7 config-0-settings.srl:539'),  # spec 15.4.7 config-0-settings.srl:539
            ('put', 'cstr', ('X',), '15.4.7 config-0-settings.srl:540'),  # spec 15.4.7 config-0-settings.srl:540
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:541'),  # spec 15.4.7 config-0-settings.srl:541
            ('put', 'f64', (0.001,), '15.4.7 config-0-settings.srl:542'),  # spec 15.4.7 config-0-settings.srl:542
            ('put', 'u32', (0, 1), '15.4.7 config-0-settings.srl:543'),  # spec 15.4.7 config-0-settings.srl:543
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:544'),  # spec 15.4.7 config-0-settings.srl:544
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:545'),  # spec 15.4.7 config-0-settings.srl:545
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:546'),  # spec 15.4.7 config-0-settings.srl:546
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:547'),  # spec 15.4.7 config-0-settings.srl:547
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:548'),  # spec 15.4.7 config-0-settings.srl:548
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:549'),  # spec 15.4.7 config-0-settings.srl:549
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:550'),  # spec 15.4.7 config-0-settings.srl:550
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:551'),  # spec 15.4.7 config-0-settings.srl:551
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:552'),  # spec 15.4.7 config-0-settings.srl:552
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:553'),  # spec 15.4.7 config-0-settings.srl:553
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:554'),  # spec 15.4.7 config-0-settings.srl:554
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:555'),  # spec 15.4.7 config-0-settings.srl:555
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:556'),  # spec 15.4.7 config-0-settings.srl:556
            ('put', 'u32', (400, 0, 0, 10, 0), '15.4.7 config-0-settings.srl:557'),  # spec 15.4.7 config-0-settings.srl:557
            ('put', 'f64', (0.01016,), '15.4.7 config-0-settings.srl:558'),  # spec 15.4.7 config-0-settings.srl:558
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:559'),  # spec 15.4.7 config-0-settings.srl:559
            ('put', 'f64', (0.001,), '15.4.7 config-0-settings.srl:560'),  # spec 15.4.7 config-0-settings.srl:560
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:561'),  # spec 15.4.7 config-0-settings.srl:561
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:562'),  # spec 15.4.7 config-0-settings.srl:562
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:563'),  # spec 15.4.7 config-0-settings.srl:563
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:564'),  # spec 15.4.7 config-0-settings.srl:564
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:565'),  # spec 15.4.7 config-0-settings.srl:565
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:566'),  # spec 15.4.7 config-0-settings.srl:566
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:567'),  # spec 15.4.7 config-0-settings.srl:567
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:568'),  # spec 15.4.7 config-0-settings.srl:568
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:569'),  # spec 15.4.7 config-0-settings.srl:569
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:570'),  # spec 15.4.7 config-0-settings.srl:570
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:571'),  # spec 15.4.7 config-0-settings.srl:571
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:572'),  # spec 15.4.7 config-0-settings.srl:572
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:573'),  # spec 15.4.7 config-0-settings.srl:573
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:574'),  # spec 15.4.7 config-0-settings.srl:574
            ('put', 'u32', (400, 0, 0, 1, 0, 1, 0, 0), '15.4.7 config-0-settings.srl:575'),  # spec 15.4.7 config-0-settings.srl:575
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:576'),  # spec 15.4.7 config-0-settings.srl:576
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:577'),  # spec 15.4.7 config-0-settings.srl:577
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:578'),  # spec 15.4.7 config-0-settings.srl:578
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:579'),  # spec 15.4.7 config-0-settings.srl:579
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:580'),  # spec 15.4.7 config-0-settings.srl:580
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:581'),  # spec 15.4.7 config-0-settings.srl:581
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:582'),  # spec 15.4.7 config-0-settings.srl:582
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:583'),  # spec 15.4.7 config-0-settings.srl:583
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:584'),  # spec 15.4.7 config-0-settings.srl:584
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:585'),  # spec 15.4.7 config-0-settings.srl:585
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:586'),  # spec 15.4.7 config-0-settings.srl:586
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:587'),  # spec 15.4.7 config-0-settings.srl:587
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:588'),  # spec 15.4.7 config-0-settings.srl:588
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:589'),  # spec 15.4.7 config-0-settings.srl:589
            ('put', 'u32', (400, 0, 1, 1, 65582), '15.4.7 config-0-settings.srl:590'),  # spec 15.4.7 config-0-settings.srl:590
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:591'),  # spec 15.4.7 config-0-settings.srl:591
            ('put', 'f32', (8873.5,), '15.4.7 config-0-settings.srl:592'),  # spec 15.4.7 config-0-settings.srl:592
            ('hex', '25', '15.4.7 config-0-settings.srl:593'),  # spec 15.4.7 config-0-settings.srl:593
            ('put', 'f32', (0.9766,), '15.4.7 config-0-settings.srl:594'),  # spec 15.4.7 config-0-settings.srl:594
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:595'),  # spec 15.4.7 config-0-settings.srl:595
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:596'),  # spec 15.4.7 config-0-settings.srl:596
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:597'),  # spec 15.4.7 config-0-settings.srl:597
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:598'),  # spec 15.4.7 config-0-settings.srl:598
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:599'),  # spec 15.4.7 config-0-settings.srl:599
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:600'),  # spec 15.4.7 config-0-settings.srl:600
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:601'),  # spec 15.4.7 config-0-settings.srl:601
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:602'),  # spec 15.4.7 config-0-settings.srl:602
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:603'),  # spec 15.4.7 config-0-settings.srl:603
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:604'),  # spec 15.4.7 config-0-settings.srl:604
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:605'),  # spec 15.4.7 config-0-settings.srl:605
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:606'),  # spec 15.4.7 config-0-settings.srl:606
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:607'),  # spec 15.4.7 config-0-settings.srl:607
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:608'),  # spec 15.4.7 config-0-settings.srl:608
            ('put', 'f64', (1.0, 1.0), '15.4.7 config-0-settings.srl:609'),  # spec 15.4.7 config-0-settings.srl:609
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:610'),  # spec 15.4.7 config-0-settings.srl:610
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:611'),  # spec 15.4.7 config-0-settings.srl:611
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:612'),  # spec 15.4.7 config-0-settings.srl:612
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:613'),  # spec 15.4.7 config-0-settings.srl:613
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:614'),  # spec 15.4.7 config-0-settings.srl:614
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:615'),  # spec 15.4.7 config-0-settings.srl:615
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:616'),  # spec 15.4.7 config-0-settings.srl:616
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:617'),  # spec 15.4.7 config-0-settings.srl:617
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:618'),  # spec 15.4.7 config-0-settings.srl:618
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:619'),  # spec 15.4.7 config-0-settings.srl:619
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:620'),  # spec 15.4.7 config-0-settings.srl:620
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:621'),  # spec 15.4.7 config-0-settings.srl:621
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:622'),  # spec 15.4.7 config-0-settings.srl:622
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:623'),  # spec 15.4.7 config-0-settings.srl:623
            ('put', 'u32', (400, 0, 0), '15.4.7 config-0-settings.srl:624'),  # spec 15.4.7 config-0-settings.srl:624
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:625'),  # spec 15.4.7 config-0-settings.srl:625
            ('put', 'f64', (0.00212,), '15.4.7 config-0-settings.srl:626'),  # spec 15.4.7 config-0-settings.srl:626
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:627'),  # spec 15.4.7 config-0-settings.srl:627
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:628'),  # spec 15.4.7 config-0-settings.srl:628
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:629'),  # spec 15.4.7 config-0-settings.srl:629
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:630'),  # spec 15.4.7 config-0-settings.srl:630
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:631'),  # spec 15.4.7 config-0-settings.srl:631
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:632'),  # spec 15.4.7 config-0-settings.srl:632
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:633'),  # spec 15.4.7 config-0-settings.srl:633
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:634'),  # spec 15.4.7 config-0-settings.srl:634
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:635'),  # spec 15.4.7 config-0-settings.srl:635
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:636'),  # spec 15.4.7 config-0-settings.srl:636
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:637'),  # spec 15.4.7 config-0-settings.srl:637
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:638'),  # spec 15.4.7 config-0-settings.srl:638
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:639'),  # spec 15.4.7 config-0-settings.srl:639
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:640'),  # spec 15.4.7 config-0-settings.srl:640
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:641'),  # spec 15.4.7 config-0-settings.srl:641
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:642'),  # spec 15.4.7 config-0-settings.srl:642
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:643'),  # spec 15.4.7 config-0-settings.srl:643
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:644'),  # spec 15.4.7 config-0-settings.srl:644
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:645'),  # spec 15.4.7 config-0-settings.srl:645
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:646'),  # spec 15.4.7 config-0-settings.srl:646
            ('put', 'f64', (0.01016,), '15.4.7 config-0-settings.srl:647'),  # spec 15.4.7 config-0-settings.srl:647
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:648'),  # spec 15.4.7 config-0-settings.srl:648
            ('put', 'f64', (0.00635,), '15.4.7 config-0-settings.srl:649'),  # spec 15.4.7 config-0-settings.srl:649
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:650'),  # spec 15.4.7 config-0-settings.srl:650
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:651'),  # spec 15.4.7 config-0-settings.srl:651
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:652'),  # spec 15.4.7 config-0-settings.srl:652
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:653'),  # spec 15.4.7 config-0-settings.srl:653
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:654'),  # spec 15.4.7 config-0-settings.srl:654
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:655'),  # spec 15.4.7 config-0-settings.srl:655
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:656'),  # spec 15.4.7 config-0-settings.srl:656
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:657'),  # spec 15.4.7 config-0-settings.srl:657
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:658'),  # spec 15.4.7 config-0-settings.srl:658
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:659'),  # spec 15.4.7 config-0-settings.srl:659
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:660'),  # spec 15.4.7 config-0-settings.srl:660
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:661'),  # spec 15.4.7 config-0-settings.srl:661
            ('put', 'u32', (400, 0, 1), '15.4.7 config-0-settings.srl:662'),  # spec 15.4.7 config-0-settings.srl:662
            ('put', 'f64', (0.00625,), '15.4.7 config-0-settings.srl:663'),  # spec 15.4.7 config-0-settings.srl:663
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:664'),  # spec 15.4.7 config-0-settings.srl:664
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:665'),  # spec 15.4.7 config-0-settings.srl:665
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:666'),  # spec 15.4.7 config-0-settings.srl:666
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:667'),  # spec 15.4.7 config-0-settings.srl:667
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:668'),  # spec 15.4.7 config-0-settings.srl:668
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:669'),  # spec 15.4.7 config-0-settings.srl:669
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:670'),  # spec 15.4.7 config-0-settings.srl:670
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:671'),  # spec 15.4.7 config-0-settings.srl:671
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:672'),  # spec 15.4.7 config-0-settings.srl:672
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:673'),  # spec 15.4.7 config-0-settings.srl:673
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:674'),  # spec 15.4.7 config-0-settings.srl:674
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:675'),  # spec 15.4.7 config-0-settings.srl:675
            ('put', 'u32', (400, 0), '15.4.7 config-0-settings.srl:676'),  # spec 15.4.7 config-0-settings.srl:676
            ('put', 'f64', (0.00508,), '15.4.7 config-0-settings.srl:677'),  # spec 15.4.7 config-0-settings.srl:677
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:678'),  # spec 15.4.7 config-0-settings.srl:678
            ('put', 'f64', (0.00625,), '15.4.7 config-0-settings.srl:679'),  # spec 15.4.7 config-0-settings.srl:679
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:680'),  # spec 15.4.7 config-0-settings.srl:680
            ('put', 'u32', (65535,), '15.4.7 config-0-settings.srl:681'),  # spec 15.4.7 config-0-settings.srl:681
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:682'),  # spec 15.4.7 config-0-settings.srl:682
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:683'),  # spec 15.4.7 config-0-settings.srl:683
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:684'),  # spec 15.4.7 config-0-settings.srl:684
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:685'),  # spec 15.4.7 config-0-settings.srl:685
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:686'),  # spec 15.4.7 config-0-settings.srl:686
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:687'),  # spec 15.4.7 config-0-settings.srl:687
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:688'),  # spec 15.4.7 config-0-settings.srl:688
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:689'),  # spec 15.4.7 config-0-settings.srl:689
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:690'),  # spec 15.4.7 config-0-settings.srl:690
            ('put', 'u32', (400, 0, 7, 9, 11, 2), '15.4.7 config-0-settings.srl:691'),  # spec 15.4.7 config-0-settings.srl:691
            ('put', 'f64', (0.01016,), '15.4.7 config-0-settings.srl:692'),  # spec 15.4.7 config-0-settings.srl:692
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:693'),  # spec 15.4.7 config-0-settings.srl:693
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:694'),  # spec 15.4.7 config-0-settings.srl:694
            ('put', 'u32', (1, 1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:695'),  # spec 15.4.7 config-0-settings.srl:695
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:696'),  # spec 15.4.7 config-0-settings.srl:696
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:697'),  # spec 15.4.7 config-0-settings.srl:697
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:698'),  # spec 15.4.7 config-0-settings.srl:698
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:699'),  # spec 15.4.7 config-0-settings.srl:699
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:700'),  # spec 15.4.7 config-0-settings.srl:700
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:701'),  # spec 15.4.7 config-0-settings.srl:701
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:702'),  # spec 15.4.7 config-0-settings.srl:702
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:703'),  # spec 15.4.7 config-0-settings.srl:703
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:704'),  # spec 15.4.7 config-0-settings.srl:704
            ('put', 'u32', (400, 1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:705'),  # spec 15.4.7 config-0-settings.srl:705
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:706'),  # spec 15.4.7 config-0-settings.srl:706
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:707'),  # spec 15.4.7 config-0-settings.srl:707
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:708'),  # spec 15.4.7 config-0-settings.srl:708
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:709'),  # spec 15.4.7 config-0-settings.srl:709
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:710'),  # spec 15.4.7 config-0-settings.srl:710
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:711'),  # spec 15.4.7 config-0-settings.srl:711
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:712'),  # spec 15.4.7 config-0-settings.srl:712
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:713'),  # spec 15.4.7 config-0-settings.srl:713
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:714'),  # spec 15.4.7 config-0-settings.srl:714
            ('put', 'u32', (400, 0, 0, 1, 0, 0), '15.4.7 config-0-settings.srl:715'),  # spec 15.4.7 config-0-settings.srl:715
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:716'),  # spec 15.4.7 config-0-settings.srl:716
            ('put', 'u32', (1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:717'),  # spec 15.4.7 config-0-settings.srl:717
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:718'),  # spec 15.4.7 config-0-settings.srl:718
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:719'),  # spec 15.4.7 config-0-settings.srl:719
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:720'),  # spec 15.4.7 config-0-settings.srl:720
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:721'),  # spec 15.4.7 config-0-settings.srl:721
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:722'),  # spec 15.4.7 config-0-settings.srl:722
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:723'),  # spec 15.4.7 config-0-settings.srl:723
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:724'),  # spec 15.4.7 config-0-settings.srl:724
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:725'),  # spec 15.4.7 config-0-settings.srl:725
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:726'),  # spec 15.4.7 config-0-settings.srl:726
            ('put', 'u32', (400, 0), '15.4.7 config-0-settings.srl:727'),  # spec 15.4.7 config-0-settings.srl:727
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:728'),  # spec 15.4.7 config-0-settings.srl:728
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:729'),  # spec 15.4.7 config-0-settings.srl:729
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:730'),  # spec 15.4.7 config-0-settings.srl:730
            ('put', 'u32', (1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:731'),  # spec 15.4.7 config-0-settings.srl:731
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:732'),  # spec 15.4.7 config-0-settings.srl:732
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:733'),  # spec 15.4.7 config-0-settings.srl:733
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:734'),  # spec 15.4.7 config-0-settings.srl:734
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:735'),  # spec 15.4.7 config-0-settings.srl:735
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:736'),  # spec 15.4.7 config-0-settings.srl:736
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:737'),  # spec 15.4.7 config-0-settings.srl:737
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:738'),  # spec 15.4.7 config-0-settings.srl:738
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:739'),  # spec 15.4.7 config-0-settings.srl:739
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:740'),  # spec 15.4.7 config-0-settings.srl:740
            ('put', 'u32', (400, 0, 0), '15.4.7 config-0-settings.srl:741'),  # spec 15.4.7 config-0-settings.srl:741
            ('put', 'f64', (0.008, 0.78539816339745), '15.4.7 config-0-settings.srl:742'),  # spec 15.4.7 config-0-settings.srl:742
            ('put', 'u32', (0, 0, 2, 1, 1, 1, 0, 0), '15.4.7 config-0-settings.srl:743'),  # spec 15.4.7 config-0-settings.srl:743
            ('put', 'u32', (2, 0), '15.4.7 config-0-settings.srl:744'),  # spec 15.4.7 config-0-settings.srl:744
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:745'),  # spec 15.4.7 config-0-settings.srl:745
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:746'),  # spec 15.4.7 config-0-settings.srl:746
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:747'),  # spec 15.4.7 config-0-settings.srl:747
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:748'),  # spec 15.4.7 config-0-settings.srl:748
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:749'),  # spec 15.4.7 config-0-settings.srl:749
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:750'),  # spec 15.4.7 config-0-settings.srl:750
            ('put', 'u32', (400, 1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:751'),  # spec 15.4.7 config-0-settings.srl:751
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:752'),  # spec 15.4.7 config-0-settings.srl:752
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:753'),  # spec 15.4.7 config-0-settings.srl:753
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:754'),  # spec 15.4.7 config-0-settings.srl:754
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:755'),  # spec 15.4.7 config-0-settings.srl:755
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:756'),  # spec 15.4.7 config-0-settings.srl:756
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:757'),  # spec 15.4.7 config-0-settings.srl:757
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:758'),  # spec 15.4.7 config-0-settings.srl:758
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:759'),  # spec 15.4.7 config-0-settings.srl:759
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:760'),  # spec 15.4.7 config-0-settings.srl:760
            ('put', 'u32', (400, 1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:761'),  # spec 15.4.7 config-0-settings.srl:761
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:762'),  # spec 15.4.7 config-0-settings.srl:762
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:763'),  # spec 15.4.7 config-0-settings.srl:763
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:764'),  # spec 15.4.7 config-0-settings.srl:764
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:765'),  # spec 15.4.7 config-0-settings.srl:765
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:766'),  # spec 15.4.7 config-0-settings.srl:766
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:767'),  # spec 15.4.7 config-0-settings.srl:767
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:768'),  # spec 15.4.7 config-0-settings.srl:768
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:769'),  # spec 15.4.7 config-0-settings.srl:769
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:770'),  # spec 15.4.7 config-0-settings.srl:770
            ('put', 'u32', (400, 0, 1, 0, 0, 65535, 0), '15.4.7 config-0-settings.srl:771'),  # spec 15.4.7 config-0-settings.srl:771
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:772'),  # spec 15.4.7 config-0-settings.srl:772
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:773'),  # spec 15.4.7 config-0-settings.srl:773
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:774'),  # spec 15.4.7 config-0-settings.srl:774
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:775'),  # spec 15.4.7 config-0-settings.srl:775
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:776'),  # spec 15.4.7 config-0-settings.srl:776
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:777'),  # spec 15.4.7 config-0-settings.srl:777
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:778'),  # spec 15.4.7 config-0-settings.srl:778
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:779'),  # spec 15.4.7 config-0-settings.srl:779
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:780'),  # spec 15.4.7 config-0-settings.srl:780
            ('put', 'u32', (400, 2, 2, 0, 2, 1, 0, 0), '15.4.7 config-0-settings.srl:781'),  # spec 15.4.7 config-0-settings.srl:781
            ('put', 'u32', (65535, 0), '15.4.7 config-0-settings.srl:782'),  # spec 15.4.7 config-0-settings.srl:782
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:783'),  # spec 15.4.7 config-0-settings.srl:783
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:784'),  # spec 15.4.7 config-0-settings.srl:784
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:785'),  # spec 15.4.7 config-0-settings.srl:785
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:786'),  # spec 15.4.7 config-0-settings.srl:786
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:787'),  # spec 15.4.7 config-0-settings.srl:787
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:788'),  # spec 15.4.7 config-0-settings.srl:788
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:789'),  # spec 15.4.7 config-0-settings.srl:789
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:790'),  # spec 15.4.7 config-0-settings.srl:790
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:791'),  # spec 15.4.7 config-0-settings.srl:791
            ('put', 'u32', (400, 0, 0), '15.4.7 config-0-settings.srl:792'),  # spec 15.4.7 config-0-settings.srl:792
            ('put', 'f64', (0.008, 0.78539816339745), '15.4.7 config-0-settings.srl:793'),  # spec 15.4.7 config-0-settings.srl:793
            ('put', 'u32', (0, 0, 2, 0, 2, 1), '15.4.7 config-0-settings.srl:794'),  # spec 15.4.7 config-0-settings.srl:794
            ('put', 'f64', (0.0005, 0.001), '15.4.7 config-0-settings.srl:795'),  # spec 15.4.7 config-0-settings.srl:795
            ('put', 'u32', (1, 1, 2, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:796'),  # spec 15.4.7 config-0-settings.srl:796
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:797'),  # spec 15.4.7 config-0-settings.srl:797
            ('put', 'u32', (1, 0, 0), '15.4.7 config-0-settings.srl:798'),  # spec 15.4.7 config-0-settings.srl:798
            ('hex', 'FFFF', '15.4.7 config-0-settings.srl:799'),  # spec 15.4.7 config-0-settings.srl:799
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:800'),  # spec 15.4.7 config-0-settings.srl:800
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:801'),  # spec 15.4.7 config-0-settings.srl:801
            ('put', 'u32', (4, 0, 0), '15.4.7 config-0-settings.srl:802'),  # spec 15.4.7 config-0-settings.srl:802
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:803'),  # spec 15.4.7 config-0-settings.srl:803
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:804'),  # spec 15.4.7 config-0-settings.srl:804
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:805'),  # spec 15.4.7 config-0-settings.srl:805
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:806'),  # spec 15.4.7 config-0-settings.srl:806
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:807'),  # spec 15.4.7 config-0-settings.srl:807
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:808'),  # spec 15.4.7 config-0-settings.srl:808
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:809'),  # spec 15.4.7 config-0-settings.srl:809
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:810'),  # spec 15.4.7 config-0-settings.srl:810
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:811'),  # spec 15.4.7 config-0-settings.srl:811
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:812'),  # spec 15.4.7 config-0-settings.srl:812
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:813'),  # spec 15.4.7 config-0-settings.srl:813
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:814'),  # spec 15.4.7 config-0-settings.srl:814
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:815'),  # spec 15.4.7 config-0-settings.srl:815
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:816'),  # spec 15.4.7 config-0-settings.srl:816
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:817'),  # spec 15.4.7 config-0-settings.srl:817
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:818'),  # spec 15.4.7 config-0-settings.srl:818
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:819'),  # spec 15.4.7 config-0-settings.srl:819
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:820'),  # spec 15.4.7 config-0-settings.srl:820
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:821'),  # spec 15.4.7 config-0-settings.srl:821
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:822'),  # spec 15.4.7 config-0-settings.srl:822
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:823'),  # spec 15.4.7 config-0-settings.srl:823
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:824'),  # spec 15.4.7 config-0-settings.srl:824
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:825'),  # spec 15.4.7 config-0-settings.srl:825
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:826'),  # spec 15.4.7 config-0-settings.srl:826
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:827'),  # spec 15.4.7 config-0-settings.srl:827
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:828'),  # spec 15.4.7 config-0-settings.srl:828
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:829'),  # spec 15.4.7 config-0-settings.srl:829
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:830'),  # spec 15.4.7 config-0-settings.srl:830
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:831'),  # spec 15.4.7 config-0-settings.srl:831
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:832'),  # spec 15.4.7 config-0-settings.srl:832
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:833'),  # spec 15.4.7 config-0-settings.srl:833
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:834'),  # spec 15.4.7 config-0-settings.srl:834
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:835'),  # spec 15.4.7 config-0-settings.srl:835
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:836'),  # spec 15.4.7 config-0-settings.srl:836
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:837'),  # spec 15.4.7 config-0-settings.srl:837
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:838'),  # spec 15.4.7 config-0-settings.srl:838
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:839'),  # spec 15.4.7 config-0-settings.srl:839
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:840'),  # spec 15.4.7 config-0-settings.srl:840
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:841'),  # spec 15.4.7 config-0-settings.srl:841
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:842'),  # spec 15.4.7 config-0-settings.srl:842
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:843'),  # spec 15.4.7 config-0-settings.srl:843
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:844'),  # spec 15.4.7 config-0-settings.srl:844
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:845'),  # spec 15.4.7 config-0-settings.srl:845
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:846'),  # spec 15.4.7 config-0-settings.srl:846
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:847'),  # spec 15.4.7 config-0-settings.srl:847
            ('put', 'u32', (400, 0, 0, 2, 2, 1, 1, 1), '15.4.7 config-0-settings.srl:848'),  # spec 15.4.7 config-0-settings.srl:848
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:849'),  # spec 15.4.7 config-0-settings.srl:849
            ('put', 'u32', (1, 3, 0), '15.4.7 config-0-settings.srl:850'),  # spec 15.4.7 config-0-settings.srl:850
            ('hex', 'FFFF', '15.4.7 config-0-settings.srl:851'),  # spec 15.4.7 config-0-settings.srl:851
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:852'),  # spec 15.4.7 config-0-settings.srl:852
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:853'),  # spec 15.4.7 config-0-settings.srl:853
            ('put', 'u32', (4, 0, 0), '15.4.7 config-0-settings.srl:854'),  # spec 15.4.7 config-0-settings.srl:854
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:855'),  # spec 15.4.7 config-0-settings.srl:855
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:856'),  # spec 15.4.7 config-0-settings.srl:856
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:857'),  # spec 15.4.7 config-0-settings.srl:857
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:858'),  # spec 15.4.7 config-0-settings.srl:858
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:859'),  # spec 15.4.7 config-0-settings.srl:859
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:860'),  # spec 15.4.7 config-0-settings.srl:860
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:861'),  # spec 15.4.7 config-0-settings.srl:861
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:862'),  # spec 15.4.7 config-0-settings.srl:862
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:863'),  # spec 15.4.7 config-0-settings.srl:863
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:864'),  # spec 15.4.7 config-0-settings.srl:864
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:865'),  # spec 15.4.7 config-0-settings.srl:865
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:866'),  # spec 15.4.7 config-0-settings.srl:866
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:867'),  # spec 15.4.7 config-0-settings.srl:867
            ('put', 'u32', (400, 2), '15.4.7 config-0-settings.srl:868'),  # spec 15.4.7 config-0-settings.srl:868
            ('put', 'f64', (-0.007812500000085043,), '15.4.7 config-0-settings.srl:869'),  # spec 15.4.7 config-0-settings.srl:869
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:870'),  # spec 15.4.7 config-0-settings.srl:870
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:871'),  # spec 15.4.7 config-0-settings.srl:871
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:872'),  # spec 15.4.7 config-0-settings.srl:872
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:873'),  # spec 15.4.7 config-0-settings.srl:873
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:874'),  # spec 15.4.7 config-0-settings.srl:874
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:875'),  # spec 15.4.7 config-0-settings.srl:875
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:876'),  # spec 15.4.7 config-0-settings.srl:876
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:877'),  # spec 15.4.7 config-0-settings.srl:877
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:878'),  # spec 15.4.7 config-0-settings.srl:878
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:879'),  # spec 15.4.7 config-0-settings.srl:879
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:880'),  # spec 15.4.7 config-0-settings.srl:880
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:881'),  # spec 15.4.7 config-0-settings.srl:881
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:882'),  # spec 15.4.7 config-0-settings.srl:882
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:883'),  # spec 15.4.7 config-0-settings.srl:883
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:884'),  # spec 15.4.7 config-0-settings.srl:884
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:885'),  # spec 15.4.7 config-0-settings.srl:885
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:886'),  # spec 15.4.7 config-0-settings.srl:886
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:887'),  # spec 15.4.7 config-0-settings.srl:887
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:888'),  # spec 15.4.7 config-0-settings.srl:888
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:889'),  # spec 15.4.7 config-0-settings.srl:889
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:890'),  # spec 15.4.7 config-0-settings.srl:890
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:891'),  # spec 15.4.7 config-0-settings.srl:891
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:892'),  # spec 15.4.7 config-0-settings.srl:892
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:893'),  # spec 15.4.7 config-0-settings.srl:893
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:894'),  # spec 15.4.7 config-0-settings.srl:894
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:895'),  # spec 15.4.7 config-0-settings.srl:895
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:896'),  # spec 15.4.7 config-0-settings.srl:896
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:897'),  # spec 15.4.7 config-0-settings.srl:897
            ('put', 'f64', (0.00635, 0.002032, 0.0127), '15.4.7 config-0-settings.srl:898'),  # spec 15.4.7 config-0-settings.srl:898
            ('put', 'u32', (0, 2, 1, 1, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:899'),  # spec 15.4.7 config-0-settings.srl:899
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:900'),  # spec 15.4.7 config-0-settings.srl:900
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:901'),  # spec 15.4.7 config-0-settings.srl:901
            ('put', 'u32', (1, 0, 0), '15.4.7 config-0-settings.srl:902'),  # spec 15.4.7 config-0-settings.srl:902
            ('hex', 'FFFF', '15.4.7 config-0-settings.srl:903'),  # spec 15.4.7 config-0-settings.srl:903
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:904'),  # spec 15.4.7 config-0-settings.srl:904
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:905'),  # spec 15.4.7 config-0-settings.srl:905
            ('put', 'u32', (4, 1, 0), '15.4.7 config-0-settings.srl:906'),  # spec 15.4.7 config-0-settings.srl:906
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:907'),  # spec 15.4.7 config-0-settings.srl:907
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:908'),  # spec 15.4.7 config-0-settings.srl:908
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:909'),  # spec 15.4.7 config-0-settings.srl:909
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:910'),  # spec 15.4.7 config-0-settings.srl:910
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:911'),  # spec 15.4.7 config-0-settings.srl:911
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:912'),  # spec 15.4.7 config-0-settings.srl:912
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:913'),  # spec 15.4.7 config-0-settings.srl:913
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:914'),  # spec 15.4.7 config-0-settings.srl:914
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:915'),  # spec 15.4.7 config-0-settings.srl:915
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:916'),  # spec 15.4.7 config-0-settings.srl:916
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:917'),  # spec 15.4.7 config-0-settings.srl:917
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:918'),  # spec 15.4.7 config-0-settings.srl:918
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:919'),  # spec 15.4.7 config-0-settings.srl:919
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:920'),  # spec 15.4.7 config-0-settings.srl:920
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:921'),  # spec 15.4.7 config-0-settings.srl:921
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:922'),  # spec 15.4.7 config-0-settings.srl:922
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:923'),  # spec 15.4.7 config-0-settings.srl:923
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:924'),  # spec 15.4.7 config-0-settings.srl:924
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:925'),  # spec 15.4.7 config-0-settings.srl:925
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:926'),  # spec 15.4.7 config-0-settings.srl:926
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:927'),  # spec 15.4.7 config-0-settings.srl:927
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:928'),  # spec 15.4.7 config-0-settings.srl:928
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:929'),  # spec 15.4.7 config-0-settings.srl:929
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:930'),  # spec 15.4.7 config-0-settings.srl:930
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:931'),  # spec 15.4.7 config-0-settings.srl:931
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:932'),  # spec 15.4.7 config-0-settings.srl:932
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:933'),  # spec 15.4.7 config-0-settings.srl:933
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:934'),  # spec 15.4.7 config-0-settings.srl:934
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:935'),  # spec 15.4.7 config-0-settings.srl:935
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:936'),  # spec 15.4.7 config-0-settings.srl:936
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:937'),  # spec 15.4.7 config-0-settings.srl:937
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:938'),  # spec 15.4.7 config-0-settings.srl:938
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:939'),  # spec 15.4.7 config-0-settings.srl:939
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:940'),  # spec 15.4.7 config-0-settings.srl:940
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:941'),  # spec 15.4.7 config-0-settings.srl:941
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:942'),  # spec 15.4.7 config-0-settings.srl:942
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:943'),  # spec 15.4.7 config-0-settings.srl:943
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:944'),  # spec 15.4.7 config-0-settings.srl:944
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:945'),  # spec 15.4.7 config-0-settings.srl:945
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:946'),  # spec 15.4.7 config-0-settings.srl:946
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:947'),  # spec 15.4.7 config-0-settings.srl:947
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:948'),  # spec 15.4.7 config-0-settings.srl:948
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:949'),  # spec 15.4.7 config-0-settings.srl:949
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:950'),  # spec 15.4.7 config-0-settings.srl:950
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:951'),  # spec 15.4.7 config-0-settings.srl:951
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:952'),  # spec 15.4.7 config-0-settings.srl:952
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:953'),  # spec 15.4.7 config-0-settings.srl:953
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:954'),  # spec 15.4.7 config-0-settings.srl:954
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:955'),  # spec 15.4.7 config-0-settings.srl:955
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:956'),  # spec 15.4.7 config-0-settings.srl:956
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:957'),  # spec 15.4.7 config-0-settings.srl:957
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:958'),  # spec 15.4.7 config-0-settings.srl:958
            ('put', 'u32', (400, 0, 0, 1, 1, 1), '15.4.7 config-0-settings.srl:959'),  # spec 15.4.7 config-0-settings.srl:959
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:960'),  # spec 15.4.7 config-0-settings.srl:960
            ('put', 'u32', (1, 0, 0), '15.4.7 config-0-settings.srl:961'),  # spec 15.4.7 config-0-settings.srl:961
            ('hex', 'FFFF', '15.4.7 config-0-settings.srl:962'),  # spec 15.4.7 config-0-settings.srl:962
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:963'),  # spec 15.4.7 config-0-settings.srl:963
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:964'),  # spec 15.4.7 config-0-settings.srl:964
            ('put', 'u32', (4, 0, 0), '15.4.7 config-0-settings.srl:965'),  # spec 15.4.7 config-0-settings.srl:965
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:966'),  # spec 15.4.7 config-0-settings.srl:966
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:967'),  # spec 15.4.7 config-0-settings.srl:967
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:968'),  # spec 15.4.7 config-0-settings.srl:968
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:969'),  # spec 15.4.7 config-0-settings.srl:969
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:970'),  # spec 15.4.7 config-0-settings.srl:970
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:971'),  # spec 15.4.7 config-0-settings.srl:971
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:972'),  # spec 15.4.7 config-0-settings.srl:972
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:973'),  # spec 15.4.7 config-0-settings.srl:973
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:974'),  # spec 15.4.7 config-0-settings.srl:974
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:975'),  # spec 15.4.7 config-0-settings.srl:975
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:976'),  # spec 15.4.7 config-0-settings.srl:976
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:977'),  # spec 15.4.7 config-0-settings.srl:977
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:978'),  # spec 15.4.7 config-0-settings.srl:978
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:979'),  # spec 15.4.7 config-0-settings.srl:979
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:980'),  # spec 15.4.7 config-0-settings.srl:980
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:981'),  # spec 15.4.7 config-0-settings.srl:981
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:982'),  # spec 15.4.7 config-0-settings.srl:982
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:983'),  # spec 15.4.7 config-0-settings.srl:983
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:984'),  # spec 15.4.7 config-0-settings.srl:984
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:985'),  # spec 15.4.7 config-0-settings.srl:985
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:986'),  # spec 15.4.7 config-0-settings.srl:986
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:987'),  # spec 15.4.7 config-0-settings.srl:987
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:988'),  # spec 15.4.7 config-0-settings.srl:988
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:989'),  # spec 15.4.7 config-0-settings.srl:989
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:990'),  # spec 15.4.7 config-0-settings.srl:990
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:991'),  # spec 15.4.7 config-0-settings.srl:991
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:992'),  # spec 15.4.7 config-0-settings.srl:992
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:993'),  # spec 15.4.7 config-0-settings.srl:993
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:994'),  # spec 15.4.7 config-0-settings.srl:994
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:995'),  # spec 15.4.7 config-0-settings.srl:995
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:996'),  # spec 15.4.7 config-0-settings.srl:996
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:997'),  # spec 15.4.7 config-0-settings.srl:997
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:998'),  # spec 15.4.7 config-0-settings.srl:998
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:999'),  # spec 15.4.7 config-0-settings.srl:999
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1000'),  # spec 15.4.7 config-0-settings.srl:1000
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1001'),  # spec 15.4.7 config-0-settings.srl:1001
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1002'),  # spec 15.4.7 config-0-settings.srl:1002
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1003'),  # spec 15.4.7 config-0-settings.srl:1003
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1004'),  # spec 15.4.7 config-0-settings.srl:1004
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1005'),  # spec 15.4.7 config-0-settings.srl:1005
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1006'),  # spec 15.4.7 config-0-settings.srl:1006
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1007'),  # spec 15.4.7 config-0-settings.srl:1007
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1008'),  # spec 15.4.7 config-0-settings.srl:1008
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1009'),  # spec 15.4.7 config-0-settings.srl:1009
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1010'),  # spec 15.4.7 config-0-settings.srl:1010
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1011'),  # spec 15.4.7 config-0-settings.srl:1011
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1012'),  # spec 15.4.7 config-0-settings.srl:1012
            ('put', 'u32', (1, 1, 1), '15.4.7 config-0-settings.srl:1013'),  # spec 15.4.7 config-0-settings.srl:1013
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:1014'),  # spec 15.4.7 config-0-settings.srl:1014
            ('put', 'u32', (1, 0, 0), '15.4.7 config-0-settings.srl:1015'),  # spec 15.4.7 config-0-settings.srl:1015
            ('hex', 'FFFF', '15.4.7 config-0-settings.srl:1016'),  # spec 15.4.7 config-0-settings.srl:1016
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1017'),  # spec 15.4.7 config-0-settings.srl:1017
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1018'),  # spec 15.4.7 config-0-settings.srl:1018
            ('put', 'u32', (4, 0, 0), '15.4.7 config-0-settings.srl:1019'),  # spec 15.4.7 config-0-settings.srl:1019
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1020'),  # spec 15.4.7 config-0-settings.srl:1020
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1021'),  # spec 15.4.7 config-0-settings.srl:1021
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1022'),  # spec 15.4.7 config-0-settings.srl:1022
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1023'),  # spec 15.4.7 config-0-settings.srl:1023
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1024'),  # spec 15.4.7 config-0-settings.srl:1024
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1025'),  # spec 15.4.7 config-0-settings.srl:1025
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1026'),  # spec 15.4.7 config-0-settings.srl:1026
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1027'),  # spec 15.4.7 config-0-settings.srl:1027
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1028'),  # spec 15.4.7 config-0-settings.srl:1028
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1029'),  # spec 15.4.7 config-0-settings.srl:1029
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1030'),  # spec 15.4.7 config-0-settings.srl:1030
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1031'),  # spec 15.4.7 config-0-settings.srl:1031
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1032'),  # spec 15.4.7 config-0-settings.srl:1032
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1033'),  # spec 15.4.7 config-0-settings.srl:1033
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1034'),  # spec 15.4.7 config-0-settings.srl:1034
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:1035'),  # spec 15.4.7 config-0-settings.srl:1035
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1036'),  # spec 15.4.7 config-0-settings.srl:1036
            ('put', 'f32', (-1,), '15.4.7 config-0-settings.srl:1037'),  # spec 15.4.7 config-0-settings.srl:1037
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1038'),  # spec 15.4.7 config-0-settings.srl:1038
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1039'),  # spec 15.4.7 config-0-settings.srl:1039
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1040'),  # spec 15.4.7 config-0-settings.srl:1040
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1041'),  # spec 15.4.7 config-0-settings.srl:1041
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1042'),  # spec 15.4.7 config-0-settings.srl:1042
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1043'),  # spec 15.4.7 config-0-settings.srl:1043
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1044'),  # spec 15.4.7 config-0-settings.srl:1044
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1045'),  # spec 15.4.7 config-0-settings.srl:1045
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1046'),  # spec 15.4.7 config-0-settings.srl:1046
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1047'),  # spec 15.4.7 config-0-settings.srl:1047
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1048'),  # spec 15.4.7 config-0-settings.srl:1048
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1049'),  # spec 15.4.7 config-0-settings.srl:1049
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1050'),  # spec 15.4.7 config-0-settings.srl:1050
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1051'),  # spec 15.4.7 config-0-settings.srl:1051
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1052'),  # spec 15.4.7 config-0-settings.srl:1052
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1053'),  # spec 15.4.7 config-0-settings.srl:1053
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1054'),  # spec 15.4.7 config-0-settings.srl:1054
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1055'),  # spec 15.4.7 config-0-settings.srl:1055
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1056'),  # spec 15.4.7 config-0-settings.srl:1056
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1057'),  # spec 15.4.7 config-0-settings.srl:1057
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1058'),  # spec 15.4.7 config-0-settings.srl:1058
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1059'),  # spec 15.4.7 config-0-settings.srl:1059
            ('put', 'f64', (0.0035,), '15.4.7 config-0-settings.srl:1060'),  # spec 15.4.7 config-0-settings.srl:1060
            ('rep', 24, 0, '15.4.7 config-0-settings.srl:1061'),  # spec 15.4.7 config-0-settings.srl:1061
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1062'),  # spec 15.4.7 config-0-settings.srl:1062
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1063'),  # spec 15.4.7 config-0-settings.srl:1063
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1064'),  # spec 15.4.7 config-0-settings.srl:1064
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1065'),  # spec 15.4.7 config-0-settings.srl:1065
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:1066'),  # spec 15.4.7 config-0-settings.srl:1066
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1067'),  # spec 15.4.7 config-0-settings.srl:1067
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1068'),  # spec 15.4.7 config-0-settings.srl:1068
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1069'),  # spec 15.4.7 config-0-settings.srl:1069
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1070'),  # spec 15.4.7 config-0-settings.srl:1070
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1071'),  # spec 15.4.7 config-0-settings.srl:1071
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1072'),  # spec 15.4.7 config-0-settings.srl:1072
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1073'),  # spec 15.4.7 config-0-settings.srl:1073
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1074'),  # spec 15.4.7 config-0-settings.srl:1074
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1075'),  # spec 15.4.7 config-0-settings.srl:1075
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1076'),  # spec 15.4.7 config-0-settings.srl:1076
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1077'),  # spec 15.4.7 config-0-settings.srl:1077
            ('hex', '01', '15.4.7 config-0-settings.srl:1078'),  # spec 15.4.7 config-0-settings.srl:1078
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1079'),  # spec 15.4.7 config-0-settings.srl:1079
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1080'),  # spec 15.4.7 config-0-settings.srl:1080
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1081'),  # spec 15.4.7 config-0-settings.srl:1081
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1082'),  # spec 15.4.7 config-0-settings.srl:1082
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1083'),  # spec 15.4.7 config-0-settings.srl:1083
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1084'),  # spec 15.4.7 config-0-settings.srl:1084
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1085'),  # spec 15.4.7 config-0-settings.srl:1085
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1086'),  # spec 15.4.7 config-0-settings.srl:1086
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1087'),  # spec 15.4.7 config-0-settings.srl:1087
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1088'),  # spec 15.4.7 config-0-settings.srl:1088
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1089'),  # spec 15.4.7 config-0-settings.srl:1089
            ('hex', '01', '15.4.7 config-0-settings.srl:1090'),  # spec 15.4.7 config-0-settings.srl:1090
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1091'),  # spec 15.4.7 config-0-settings.srl:1091
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1092'),  # spec 15.4.7 config-0-settings.srl:1092
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1093'),  # spec 15.4.7 config-0-settings.srl:1093
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1094'),  # spec 15.4.7 config-0-settings.srl:1094
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1095'),  # spec 15.4.7 config-0-settings.srl:1095
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1096'),  # spec 15.4.7 config-0-settings.srl:1096
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1097'),  # spec 15.4.7 config-0-settings.srl:1097
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1098'),  # spec 15.4.7 config-0-settings.srl:1098
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1099'),  # spec 15.4.7 config-0-settings.srl:1099
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1100'),  # spec 15.4.7 config-0-settings.srl:1100
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1101'),  # spec 15.4.7 config-0-settings.srl:1101
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1102'),  # spec 15.4.7 config-0-settings.srl:1102
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1103'),  # spec 15.4.7 config-0-settings.srl:1103
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1104'),  # spec 15.4.7 config-0-settings.srl:1104
            ('put', 'u32', (257,), '15.4.7 config-0-settings.srl:1105'),  # spec 15.4.7 config-0-settings.srl:1105
            ('rep', 14, 0, '15.4.7 config-0-settings.srl:1106'),  # spec 15.4.7 config-0-settings.srl:1106
            ('put', 'u32', (1, 512), '15.4.7 config-0-settings.srl:1107'),  # spec 15.4.7 config-0-settings.srl:1107
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1108'),  # spec 15.4.7 config-0-settings.srl:1108
            ('put', 'u32', (3, 10, 0), '15.4.7 config-0-settings.srl:1109'),  # spec 15.4.7 config-0-settings.srl:1109
            ('put', 'f64', (1e-06, 1e-06), '15.4.7 config-0-settings.srl:1110'),  # spec 15.4.7 config-0-settings.srl:1110
            ('hex', '0101', '15.4.7 config-0-settings.srl:1111'),  # spec 15.4.7 config-0-settings.srl:1111
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1112'),  # spec 15.4.7 config-0-settings.srl:1112
            ('hex', '010101', '15.4.7 config-0-settings.srl:1113'),  # spec 15.4.7 config-0-settings.srl:1113
            ('put', 'u32', (65793,), '15.4.7 config-0-settings.srl:1114'),  # spec 15.4.7 config-0-settings.srl:1114
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1115'),  # spec 15.4.7 config-0-settings.srl:1115
            ('hex', '01', '15.4.7 config-0-settings.srl:1116'),  # spec 15.4.7 config-0-settings.srl:1116
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1117'),  # spec 15.4.7 config-0-settings.srl:1117
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1118'),  # spec 15.4.7 config-0-settings.srl:1118
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1119'),  # spec 15.4.7 config-0-settings.srl:1119
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1120'),  # spec 15.4.7 config-0-settings.srl:1120
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1121'),  # spec 15.4.7 config-0-settings.srl:1121
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1122'),  # spec 15.4.7 config-0-settings.srl:1122
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1123'),  # spec 15.4.7 config-0-settings.srl:1123
            ('rep', 19, 0, '15.4.7 config-0-settings.srl:1124'),  # spec 15.4.7 config-0-settings.srl:1124
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1125'),  # spec 15.4.7 config-0-settings.srl:1125
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1126'),  # spec 15.4.7 config-0-settings.srl:1126
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1127'),  # spec 15.4.7 config-0-settings.srl:1127
            ('hex', '01', '15.4.7 config-0-settings.srl:1128'),  # spec 15.4.7 config-0-settings.srl:1128
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1129'),  # spec 15.4.7 config-0-settings.srl:1129
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1130'),  # spec 15.4.7 config-0-settings.srl:1130
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1131'),  # spec 15.4.7 config-0-settings.srl:1131
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1132'),  # spec 15.4.7 config-0-settings.srl:1132
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1133'),  # spec 15.4.7 config-0-settings.srl:1133
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1134'),  # spec 15.4.7 config-0-settings.srl:1134
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1135'),  # spec 15.4.7 config-0-settings.srl:1135
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1136'),  # spec 15.4.7 config-0-settings.srl:1136
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1137'),  # spec 15.4.7 config-0-settings.srl:1137
            ('rep', 19, 0, '15.4.7 config-0-settings.srl:1138'),  # spec 15.4.7 config-0-settings.srl:1138
            ('put', 'f64', (0.01016,), '15.4.7 config-0-settings.srl:1139'),  # spec 15.4.7 config-0-settings.srl:1139
            ('put', 'u32', (0, 1), '15.4.7 config-0-settings.srl:1140'),  # spec 15.4.7 config-0-settings.srl:1140
            ('put', 'cstr', ('X',), '15.4.7 config-0-settings.srl:1141'),  # spec 15.4.7 config-0-settings.srl:1141
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:1142'),  # spec 15.4.7 config-0-settings.srl:1142
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1143'),  # spec 15.4.7 config-0-settings.srl:1143
            ('put', 'f64', (0.001,), '15.4.7 config-0-settings.srl:1144'),  # spec 15.4.7 config-0-settings.srl:1144
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1145'),  # spec 15.4.7 config-0-settings.srl:1145
            ('rep', 3, 0, '15.4.7 config-0-settings.srl:1146'),  # spec 15.4.7 config-0-settings.srl:1146
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1147'),  # spec 15.4.7 config-0-settings.srl:1147
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1148'),  # spec 15.4.7 config-0-settings.srl:1148
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1149'),  # spec 15.4.7 config-0-settings.srl:1149
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1150'),  # spec 15.4.7 config-0-settings.srl:1150
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1151'),  # spec 15.4.7 config-0-settings.srl:1151
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1152'),  # spec 15.4.7 config-0-settings.srl:1152
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1153'),  # spec 15.4.7 config-0-settings.srl:1153
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1154'),  # spec 15.4.7 config-0-settings.srl:1154
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1155'),  # spec 15.4.7 config-0-settings.srl:1155
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1156'),  # spec 15.4.7 config-0-settings.srl:1156
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1157'),  # spec 15.4.7 config-0-settings.srl:1157
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1158'),  # spec 15.4.7 config-0-settings.srl:1158
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1159'),  # spec 15.4.7 config-0-settings.srl:1159
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1160'),  # spec 15.4.7 config-0-settings.srl:1160
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1161'),  # spec 15.4.7 config-0-settings.srl:1161
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1162'),  # spec 15.4.7 config-0-settings.srl:1162
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1163'),  # spec 15.4.7 config-0-settings.srl:1163
            ('put', 'u32', (0,), '15.4.7 config-0-settings.srl:1164'),  # spec 15.4.7 config-0-settings.srl:1164
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1165'),  # spec 15.4.7 config-0-settings.srl:1165
            ('rep', 29, 0, '15.4.7 config-0-settings.srl:1166'),  # spec 15.4.7 config-0-settings.srl:1166
            ('hex', '01', '15.4.7 config-0-settings.srl:1167'),  # spec 15.4.7 config-0-settings.srl:1167
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1168'),  # spec 15.4.7 config-0-settings.srl:1168
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1169'),  # spec 15.4.7 config-0-settings.srl:1169
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1170'),  # spec 15.4.7 config-0-settings.srl:1170
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1171'),  # spec 15.4.7 config-0-settings.srl:1171
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1172'),  # spec 15.4.7 config-0-settings.srl:1172
            ('rep', 7, 0, '15.4.7 config-0-settings.srl:1173'),  # spec 15.4.7 config-0-settings.srl:1173
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1174'),  # spec 15.4.7 config-0-settings.srl:1174
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1175'),  # spec 15.4.7 config-0-settings.srl:1175
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1176'),  # spec 15.4.7 config-0-settings.srl:1176
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1177'),  # spec 15.4.7 config-0-settings.srl:1177
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1178'),  # spec 15.4.7 config-0-settings.srl:1178
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1179'),  # spec 15.4.7 config-0-settings.srl:1179
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1180'),  # spec 15.4.7 config-0-settings.srl:1180
            ('hex', '01', '15.4.7 config-0-settings.srl:1181'),  # spec 15.4.7 config-0-settings.srl:1181
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1182'),  # spec 15.4.7 config-0-settings.srl:1182
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1183'),  # spec 15.4.7 config-0-settings.srl:1183
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1184'),  # spec 15.4.7 config-0-settings.srl:1184
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1185'),  # spec 15.4.7 config-0-settings.srl:1185
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1186'),  # spec 15.4.7 config-0-settings.srl:1186
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1187'),  # spec 15.4.7 config-0-settings.srl:1187
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1188'),  # spec 15.4.7 config-0-settings.srl:1188
            ('hex', '01', '15.4.7 config-0-settings.srl:1189'),  # spec 15.4.7 config-0-settings.srl:1189
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1190'),  # spec 15.4.7 config-0-settings.srl:1190
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1191'),  # spec 15.4.7 config-0-settings.srl:1191
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1192'),  # spec 15.4.7 config-0-settings.srl:1192
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1193'),  # spec 15.4.7 config-0-settings.srl:1193
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1194'),  # spec 15.4.7 config-0-settings.srl:1194
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1195'),  # spec 15.4.7 config-0-settings.srl:1195
            ('put', 'u32', (400, 0), '15.4.7 config-0-settings.srl:1196'),  # spec 15.4.7 config-0-settings.srl:1196
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1197'),  # spec 15.4.7 config-0-settings.srl:1197
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1198'),  # spec 15.4.7 config-0-settings.srl:1198
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1199'),  # spec 15.4.7 config-0-settings.srl:1199
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1200'),  # spec 15.4.7 config-0-settings.srl:1200
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1201'),  # spec 15.4.7 config-0-settings.srl:1201
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1202'),  # spec 15.4.7 config-0-settings.srl:1202
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1203'),  # spec 15.4.7 config-0-settings.srl:1203
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1204'),  # spec 15.4.7 config-0-settings.srl:1204
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1205'),  # spec 15.4.7 config-0-settings.srl:1205
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1206'),  # spec 15.4.7 config-0-settings.srl:1206
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1207'),  # spec 15.4.7 config-0-settings.srl:1207
            ('hex', '01', '15.4.7 config-0-settings.srl:1208'),  # spec 15.4.7 config-0-settings.srl:1208
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1209'),  # spec 15.4.7 config-0-settings.srl:1209
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1210'),  # spec 15.4.7 config-0-settings.srl:1210
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1211'),  # spec 15.4.7 config-0-settings.srl:1211
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1212'),  # spec 15.4.7 config-0-settings.srl:1212
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1213'),  # spec 15.4.7 config-0-settings.srl:1213
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1214'),  # spec 15.4.7 config-0-settings.srl:1214
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1215'),  # spec 15.4.7 config-0-settings.srl:1215
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1216'),  # spec 15.4.7 config-0-settings.srl:1216
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1217'),  # spec 15.4.7 config-0-settings.srl:1217
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1218'),  # spec 15.4.7 config-0-settings.srl:1218
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1219'),  # spec 15.4.7 config-0-settings.srl:1219
            ('hex', '01', '15.4.7 config-0-settings.srl:1220'),  # spec 15.4.7 config-0-settings.srl:1220
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1221'),  # spec 15.4.7 config-0-settings.srl:1221
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1222'),  # spec 15.4.7 config-0-settings.srl:1222
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1223'),  # spec 15.4.7 config-0-settings.srl:1223
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1224'),  # spec 15.4.7 config-0-settings.srl:1224
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1225'),  # spec 15.4.7 config-0-settings.srl:1225
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1226'),  # spec 15.4.7 config-0-settings.srl:1226
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1227'),  # spec 15.4.7 config-0-settings.srl:1227
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1228'),  # spec 15.4.7 config-0-settings.srl:1228
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1229'),  # spec 15.4.7 config-0-settings.srl:1229
            ('rep', 17, 0, '15.4.7 config-0-settings.srl:1230'),  # spec 15.4.7 config-0-settings.srl:1230
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1231'),  # spec 15.4.7 config-0-settings.srl:1231
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1232'),  # spec 15.4.7 config-0-settings.srl:1232
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1233'),  # spec 15.4.7 config-0-settings.srl:1233
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1234'),  # spec 15.4.7 config-0-settings.srl:1234
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1235'),  # spec 15.4.7 config-0-settings.srl:1235
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1236'),  # spec 15.4.7 config-0-settings.srl:1236
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1237'),  # spec 15.4.7 config-0-settings.srl:1237
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1238'),  # spec 15.4.7 config-0-settings.srl:1238
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1239'),  # spec 15.4.7 config-0-settings.srl:1239
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1240'),  # spec 15.4.7 config-0-settings.srl:1240
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1241'),  # spec 15.4.7 config-0-settings.srl:1241
            ('hex', '01', '15.4.7 config-0-settings.srl:1242'),  # spec 15.4.7 config-0-settings.srl:1242
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1243'),  # spec 15.4.7 config-0-settings.srl:1243
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1244'),  # spec 15.4.7 config-0-settings.srl:1244
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1245'),  # spec 15.4.7 config-0-settings.srl:1245
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1246'),  # spec 15.4.7 config-0-settings.srl:1246
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1247'),  # spec 15.4.7 config-0-settings.srl:1247
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1248'),  # spec 15.4.7 config-0-settings.srl:1248
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1249'),  # spec 15.4.7 config-0-settings.srl:1249
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1250'),  # spec 15.4.7 config-0-settings.srl:1250
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1251'),  # spec 15.4.7 config-0-settings.srl:1251
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1252'),  # spec 15.4.7 config-0-settings.srl:1252
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1253'),  # spec 15.4.7 config-0-settings.srl:1253
            ('hex', '01', '15.4.7 config-0-settings.srl:1254'),  # spec 15.4.7 config-0-settings.srl:1254
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1255'),  # spec 15.4.7 config-0-settings.srl:1255
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1256'),  # spec 15.4.7 config-0-settings.srl:1256
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1257'),  # spec 15.4.7 config-0-settings.srl:1257
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1258'),  # spec 15.4.7 config-0-settings.srl:1258
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1259'),  # spec 15.4.7 config-0-settings.srl:1259
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1260'),  # spec 15.4.7 config-0-settings.srl:1260
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1261'),  # spec 15.4.7 config-0-settings.srl:1261
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1262'),  # spec 15.4.7 config-0-settings.srl:1262
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1263'),  # spec 15.4.7 config-0-settings.srl:1263
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1264'),  # spec 15.4.7 config-0-settings.srl:1264
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1265'),  # spec 15.4.7 config-0-settings.srl:1265
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1266'),  # spec 15.4.7 config-0-settings.srl:1266
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1267'),  # spec 15.4.7 config-0-settings.srl:1267
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1268'),  # spec 15.4.7 config-0-settings.srl:1268
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1269'),  # spec 15.4.7 config-0-settings.srl:1269
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1270'),  # spec 15.4.7 config-0-settings.srl:1270
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1271'),  # spec 15.4.7 config-0-settings.srl:1271
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1272'),  # spec 15.4.7 config-0-settings.srl:1272
            ('rep', 30, 0, '15.4.7 config-0-settings.srl:1273'),  # spec 15.4.7 config-0-settings.srl:1273
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1274'),  # spec 15.4.7 config-0-settings.srl:1274
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1275'),  # spec 15.4.7 config-0-settings.srl:1275
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1276'),  # spec 15.4.7 config-0-settings.srl:1276
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1277'),  # spec 15.4.7 config-0-settings.srl:1277
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1278'),  # spec 15.4.7 config-0-settings.srl:1278
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1279'),  # spec 15.4.7 config-0-settings.srl:1279
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1280'),  # spec 15.4.7 config-0-settings.srl:1280
            ('rep', 30, 0, '15.4.7 config-0-settings.srl:1281'),  # spec 15.4.7 config-0-settings.srl:1281
            ('put', 'u32', (1, 2), '15.4.7 config-0-settings.srl:1282'),  # spec 15.4.7 config-0-settings.srl:1282
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1283'),  # spec 15.4.7 config-0-settings.srl:1283
            ('put', 'u32', (65792,), '15.4.7 config-0-settings.srl:1284'),  # spec 15.4.7 config-0-settings.srl:1284
            ('rep', 5, 0, '15.4.7 config-0-settings.srl:1285'),  # spec 15.4.7 config-0-settings.srl:1285
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1286'),  # spec 15.4.7 config-0-settings.srl:1286
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1287'),  # spec 15.4.7 config-0-settings.srl:1287
            ('hex', '6C', '15.4.7 config-0-settings.srl:1288'),  # spec 15.4.7 config-0-settings.srl:1288
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1289'),  # spec 15.4.7 config-0-settings.srl:1289
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1290'),  # spec 15.4.7 config-0-settings.srl:1290
            ('put', 'u8', (0,), '15.4.7 config-0-settings.srl:1291'),  # spec 15.4.7 config-0-settings.srl:1291
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1292'),  # spec 15.4.7 config-0-settings.srl:1292
            ('put', 'u32', (256,), '15.4.7 config-0-settings.srl:1293'),  # spec 15.4.7 config-0-settings.srl:1293
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1294'),  # spec 15.4.7 config-0-settings.srl:1294
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1295'),  # spec 15.4.7 config-0-settings.srl:1295
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1296'),  # spec 15.4.7 config-0-settings.srl:1296
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1297'),  # spec 15.4.7 config-0-settings.srl:1297
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1298'),  # spec 15.4.7 config-0-settings.srl:1298
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1299'),  # spec 15.4.7 config-0-settings.srl:1299
            ('put', 'u32', (400, 3), '15.4.7 config-0-settings.srl:1300'),  # spec 15.4.7 config-0-settings.srl:1300
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1301'),  # spec 15.4.7 config-0-settings.srl:1301
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1302'),  # spec 15.4.7 config-0-settings.srl:1302
            ('hex', '01', '15.4.7 config-0-settings.srl:1303'),  # spec 15.4.7 config-0-settings.srl:1303
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1304'),  # spec 15.4.7 config-0-settings.srl:1304
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1305'),  # spec 15.4.7 config-0-settings.srl:1305
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1306'),  # spec 15.4.7 config-0-settings.srl:1306
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1307'),  # spec 15.4.7 config-0-settings.srl:1307
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1308'),  # spec 15.4.7 config-0-settings.srl:1308
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1309'),  # spec 15.4.7 config-0-settings.srl:1309
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1310'),  # spec 15.4.7 config-0-settings.srl:1310
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1311'),  # spec 15.4.7 config-0-settings.srl:1311
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1312'),  # spec 15.4.7 config-0-settings.srl:1312
            ('rep', 28, 0, '15.4.7 config-0-settings.srl:1313'),  # spec 15.4.7 config-0-settings.srl:1313
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1314'),  # spec 15.4.7 config-0-settings.srl:1314
            ('rep', 11, 0, '15.4.7 config-0-settings.srl:1315'),  # spec 15.4.7 config-0-settings.srl:1315
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1316'),  # spec 15.4.7 config-0-settings.srl:1316
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1317'),  # spec 15.4.7 config-0-settings.srl:1317
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1318'),  # spec 15.4.7 config-0-settings.srl:1318
            ('hex', '01', '15.4.7 config-0-settings.srl:1319'),  # spec 15.4.7 config-0-settings.srl:1319
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1320'),  # spec 15.4.7 config-0-settings.srl:1320
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1321'),  # spec 15.4.7 config-0-settings.srl:1321
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1322'),  # spec 15.4.7 config-0-settings.srl:1322
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1323'),  # spec 15.4.7 config-0-settings.srl:1323
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1324'),  # spec 15.4.7 config-0-settings.srl:1324
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1325'),  # spec 15.4.7 config-0-settings.srl:1325
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1326'),  # spec 15.4.7 config-0-settings.srl:1326
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1327'),  # spec 15.4.7 config-0-settings.srl:1327
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1328'),  # spec 15.4.7 config-0-settings.srl:1328
            ('rep', 17, 0, '15.4.7 config-0-settings.srl:1329'),  # spec 15.4.7 config-0-settings.srl:1329
            ('put', 'u32', (65793,), '15.4.7 config-0-settings.srl:1330'),  # spec 15.4.7 config-0-settings.srl:1330
            ('rep', 19, 0, '15.4.7 config-0-settings.srl:1331'),  # spec 15.4.7 config-0-settings.srl:1331
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1332'),  # spec 15.4.7 config-0-settings.srl:1332
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1333'),  # spec 15.4.7 config-0-settings.srl:1333
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:1334'),  # spec 15.4.7 config-0-settings.srl:1334
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1335'),  # spec 15.4.7 config-0-settings.srl:1335
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1336'),  # spec 15.4.7 config-0-settings.srl:1336
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1337'),  # spec 15.4.7 config-0-settings.srl:1337
            ('hex', '01', '15.4.7 config-0-settings.srl:1338'),  # spec 15.4.7 config-0-settings.srl:1338
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1339'),  # spec 15.4.7 config-0-settings.srl:1339
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1340'),  # spec 15.4.7 config-0-settings.srl:1340
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1341'),  # spec 15.4.7 config-0-settings.srl:1341
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1342'),  # spec 15.4.7 config-0-settings.srl:1342
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1343'),  # spec 15.4.7 config-0-settings.srl:1343
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1344'),  # spec 15.4.7 config-0-settings.srl:1344
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1345'),  # spec 15.4.7 config-0-settings.srl:1345
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1346'),  # spec 15.4.7 config-0-settings.srl:1346
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1347'),  # spec 15.4.7 config-0-settings.srl:1347
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1348'),  # spec 15.4.7 config-0-settings.srl:1348
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1349'),  # spec 15.4.7 config-0-settings.srl:1349
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1350'),  # spec 15.4.7 config-0-settings.srl:1350
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1351'),  # spec 15.4.7 config-0-settings.srl:1351
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1352'),  # spec 15.4.7 config-0-settings.srl:1352
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1353'),  # spec 15.4.7 config-0-settings.srl:1353
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1354'),  # spec 15.4.7 config-0-settings.srl:1354
            ('put', 'f64', (0.03, 0.03), '15.4.7 config-0-settings.srl:1355'),  # spec 15.4.7 config-0-settings.srl:1355
            ('rep', 5, 0, '15.4.7 config-0-settings.srl:1356'),  # spec 15.4.7 config-0-settings.srl:1356
            ('hex', '01', '15.4.7 config-0-settings.srl:1357'),  # spec 15.4.7 config-0-settings.srl:1357
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1358'),  # spec 15.4.7 config-0-settings.srl:1358
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1359'),  # spec 15.4.7 config-0-settings.srl:1359
            ('rep', 9, 0, '15.4.7 config-0-settings.srl:1360'),  # spec 15.4.7 config-0-settings.srl:1360
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1361'),  # spec 15.4.7 config-0-settings.srl:1361
            ('rep', 27, 0, '15.4.7 config-0-settings.srl:1362'),  # spec 15.4.7 config-0-settings.srl:1362
            ('put', 'u32', (3,), '15.4.7 config-0-settings.srl:1363'),  # spec 15.4.7 config-0-settings.srl:1363
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1364'),  # spec 15.4.7 config-0-settings.srl:1364
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1365'),  # spec 15.4.7 config-0-settings.srl:1365
            ('hex', '01', '15.4.7 config-0-settings.srl:1366'),  # spec 15.4.7 config-0-settings.srl:1366
            ('put', 'cstr', ('Segoe UI',), '15.4.7 config-0-settings.srl:1367'),  # spec 15.4.7 config-0-settings.srl:1367
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1368'),  # spec 15.4.7 config-0-settings.srl:1368
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1369'),  # spec 15.4.7 config-0-settings.srl:1369
            ('put', 'f64', (0.001, 1.0), '15.4.7 config-0-settings.srl:1370'),  # spec 15.4.7 config-0-settings.srl:1370
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1371'),  # spec 15.4.7 config-0-settings.srl:1371
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1372'),  # spec 15.4.7 config-0-settings.srl:1372
            ('put', 'u32', (400, 1), '15.4.7 config-0-settings.srl:1373'),  # spec 15.4.7 config-0-settings.srl:1373
            ('rep', 13, 0, '15.4.7 config-0-settings.srl:1374'),  # spec 15.4.7 config-0-settings.srl:1374
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1375'),  # spec 15.4.7 config-0-settings.srl:1375
            ('rep', 11, 0, '15.4.7 config-0-settings.srl:1376'),  # spec 15.4.7 config-0-settings.srl:1376
            ('put', 'f32', (173,), '15.4.7 config-0-settings.srl:1377'),  # spec 15.4.7 config-0-settings.srl:1377
            ('hex', '1CEBE236', '15.4.7 config-0-settings.srl:1378'),  # spec 15.4.7 config-0-settings.srl:1378
            ('put', 'u32', (147210,), '15.4.7 config-0-settings.srl:1379'),  # spec 15.4.7 config-0-settings.srl:1379
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1380'),  # spec 15.4.7 config-0-settings.srl:1380
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1381'),  # spec 15.4.7 config-0-settings.srl:1381
            ('put', 'f64', (0.0001,), '15.4.7 config-0-settings.srl:1382'),  # spec 15.4.7 config-0-settings.srl:1382
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1383'),  # spec 15.4.7 config-0-settings.srl:1383
            ('put', 'f64', (0.0002,), '15.4.7 config-0-settings.srl:1384'),  # spec 15.4.7 config-0-settings.srl:1384
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1385'),  # spec 15.4.7 config-0-settings.srl:1385
            ('put', 'f64', (0.0002,), '15.4.7 config-0-settings.srl:1386'),  # spec 15.4.7 config-0-settings.srl:1386
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1387'),  # spec 15.4.7 config-0-settings.srl:1387
            ('put', 'f64', (0.0005,), '15.4.7 config-0-settings.srl:1388'),  # spec 15.4.7 config-0-settings.srl:1388
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1389'),  # spec 15.4.7 config-0-settings.srl:1389
            ('put', 'f64', (0.00025,), '15.4.7 config-0-settings.srl:1390'),  # spec 15.4.7 config-0-settings.srl:1390
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1391'),  # spec 15.4.7 config-0-settings.srl:1391
            ('put', 'f64', (0.0005,), '15.4.7 config-0-settings.srl:1392'),  # spec 15.4.7 config-0-settings.srl:1392
            ('put', 'u32', (2, 2), '15.4.7 config-0-settings.srl:1393'),  # spec 15.4.7 config-0-settings.srl:1393
            ('put', 'f64', (0.0001,), '15.4.7 config-0-settings.srl:1394'),  # spec 15.4.7 config-0-settings.srl:1394
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1395'),  # spec 15.4.7 config-0-settings.srl:1395
            ('put', 'f64', (-0.00025,), '15.4.7 config-0-settings.srl:1396'),  # spec 15.4.7 config-0-settings.srl:1396
            ('put', 'u32', (2, 2, 2), '15.4.7 config-0-settings.srl:1397'),  # spec 15.4.7 config-0-settings.srl:1397
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1398'),  # spec 15.4.7 config-0-settings.srl:1398
            ('put', 'u32', (2, 2, 2), '15.4.7 config-0-settings.srl:1399'),  # spec 15.4.7 config-0-settings.srl:1399
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1400'),  # spec 15.4.7 config-0-settings.srl:1400
            ('put', 'u32', (2, 2, 2), '15.4.7 config-0-settings.srl:1401'),  # spec 15.4.7 config-0-settings.srl:1401
            ('put', 'f64', (0.00025, -0.00025), '15.4.7 config-0-settings.srl:1402'),  # spec 15.4.7 config-0-settings.srl:1402
            ('put', 'u32', (2, 2, 2), '15.4.7 config-0-settings.srl:1403'),  # spec 15.4.7 config-0-settings.srl:1403
            ('put', 'f64', (0.0002, -0.0002), '15.4.7 config-0-settings.srl:1404'),  # spec 15.4.7 config-0-settings.srl:1404
            ('put', 'u32', (2, 2, 2, 2, 2, 2, 2), '15.4.7 config-0-settings.srl:1405'),  # spec 15.4.7 config-0-settings.srl:1405
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1406'),  # spec 15.4.7 config-0-settings.srl:1406
            ('put', 'u32', (2, 2), '15.4.7 config-0-settings.srl:1407'),  # spec 15.4.7 config-0-settings.srl:1407
            ('put', 'f64', (0.00025, -0.00025), '15.4.7 config-0-settings.srl:1408'),  # spec 15.4.7 config-0-settings.srl:1408
            ('put', 'u32', (2, 2, 2, 2), '15.4.7 config-0-settings.srl:1409'),  # spec 15.4.7 config-0-settings.srl:1409
            ('put', 'f64', (0.01, 1.0), '15.4.7 config-0-settings.srl:1410'),  # spec 15.4.7 config-0-settings.srl:1410
            ('put', 'u32', (2, 2, 2, 2, 2, 2, 2, 2), '15.4.7 config-0-settings.srl:1411'),  # spec 15.4.7 config-0-settings.srl:1411
            ('put', 'u32', (2,), '15.4.7 config-0-settings.srl:1412'),  # spec 15.4.7 config-0-settings.srl:1412
            ('rep', 36, 0, '15.4.7 config-0-settings.srl:1413'),  # spec 15.4.7 config-0-settings.srl:1413
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1414'),  # spec 15.4.7 config-0-settings.srl:1414
            ('put', 'f64', (0.0001, 0.00025, 0.00025, 0.0005, -0.0005), '15.4.7 config-0-settings.srl:1415'),  # spec 15.4.7 config-0-settings.srl:1415
            ('put', 'u32', (2, 0), '15.4.7 config-0-settings.srl:1416'),  # spec 15.4.7 config-0-settings.srl:1416
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1417'),  # spec 15.4.7 config-0-settings.srl:1417
            ('put', 'u32', (2, 2, 1, 2), '15.4.7 config-0-settings.srl:1418'),  # spec 15.4.7 config-0-settings.srl:1418
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1419'),  # spec 15.4.7 config-0-settings.srl:1419
            ('put', 'u32', (2, 2, 1, 2), '15.4.7 config-0-settings.srl:1420'),  # spec 15.4.7 config-0-settings.srl:1420
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1421'),  # spec 15.4.7 config-0-settings.srl:1421
            ('put', 'u32', (2, 2, 1, 2), '15.4.7 config-0-settings.srl:1422'),  # spec 15.4.7 config-0-settings.srl:1422
            ('put', 'f64', (0.0005, -0.0005), '15.4.7 config-0-settings.srl:1423'),  # spec 15.4.7 config-0-settings.srl:1423
            ('put', 'u32', (2, 2, 1, 2, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:1424'),  # spec 15.4.7 config-0-settings.srl:1424
            ('put', 'u32', (1, 1, 1, 1, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:1425'),  # spec 15.4.7 config-0-settings.srl:1425
            ('put', 'u32', (1, 1, 1), '15.4.7 config-0-settings.srl:1426'),  # spec 15.4.7 config-0-settings.srl:1426
            ('put', 'f64', (0.0005, -0.0005, 0.00872664625997, -0.00872664625997), '15.4.7 config-0-settings.srl:1427'),  # spec 15.4.7 config-0-settings.srl:1427
            ('put', 'u32', (2, 2, 2, 2, 1, 1, 2, 2), '15.4.7 config-0-settings.srl:1428'),  # spec 15.4.7 config-0-settings.srl:1428
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:1429'),  # spec 15.4.7 config-0-settings.srl:1429
            ('put', 'f64', (0.01745329251994, -0.01745329251994, 0.00872664625997, -0.00872664625997), '15.4.7 config-0-settings.srl:1430'),  # spec 15.4.7 config-0-settings.srl:1430
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1431'),  # spec 15.4.7 config-0-settings.srl:1431
            ('put', 'u32', (1, 1), '15.4.7 config-0-settings.srl:1432'),  # spec 15.4.7 config-0-settings.srl:1432
            ('rep', 28, 0, '15.4.7 config-0-settings.srl:1433'),  # spec 15.4.7 config-0-settings.srl:1433
            ('put', 'u32', (5,), '15.4.7 config-0-settings.srl:1434'),  # spec 15.4.7 config-0-settings.srl:1434
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1435'),  # spec 15.4.7 config-0-settings.srl:1435
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1436'),  # spec 15.4.7 config-0-settings.srl:1436
            ('put', 'f32', (0.00018, 0.00025, 0.00035, 0.0005, 0.0007, 0.001, 0.0014, 0.002), '15.4.7 config-0-settings.srl:1437'),  # spec 15.4.7 config-0-settings.srl:1437
            ('put', 'f64', (5000.0,), '15.4.7 config-0-settings.srl:1438'),  # spec 15.4.7 config-0-settings.srl:1438
            ('put', 'u32', (3, 1), '15.4.7 config-0-settings.srl:1439'),  # spec 15.4.7 config-0-settings.srl:1439
            ('rep', 2, 0, '15.4.7 config-0-settings.srl:1440'),  # spec 15.4.7 config-0-settings.srl:1440
            ('put', 'u32', (1, 0, 1, 1, 1, 1), '15.4.7 config-0-settings.srl:1441'),  # spec 15.4.7 config-0-settings.srl:1441
            ('put', 'f64', (0.0025, 0.0085, 0.0085, 0.0085, 3.0, 3.0), '15.4.7 config-0-settings.srl:1442'),  # spec 15.4.7 config-0-settings.srl:1442
            ('put', 'u32', (0, 0), '15.4.7 config-0-settings.srl:1443'),  # spec 15.4.7 config-0-settings.srl:1443
            ('put', 'i32', (-1,), '15.4.7 config-0-settings.srl:1444'),  # spec 15.4.7 config-0-settings.srl:1444
            ('put', 'u32', (0, 0, 1, 1, 1, 0), '15.4.7 config-0-settings.srl:1445'),  # spec 15.4.7 config-0-settings.srl:1445
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1446'),  # spec 15.4.7 config-0-settings.srl:1446
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1447'),  # spec 15.4.7 config-0-settings.srl:1447
            ('put', 'u32', (12,), '15.4.7 config-0-settings.srl:1448'),  # spec 15.4.7 config-0-settings.srl:1448
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1449'),  # spec 15.4.7 config-0-settings.srl:1449
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1450'),  # spec 15.4.7 config-0-settings.srl:1450
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1451'),  # spec 15.4.7 config-0-settings.srl:1451
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1452'),  # spec 15.4.7 config-0-settings.srl:1452
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1453'),  # spec 15.4.7 config-0-settings.srl:1453
            ('put', 'cstr', ('Century Gothic',), '15.4.7 config-0-settings.srl:1454'),  # spec 15.4.7 config-0-settings.srl:1454
            ('put', 'f64', (-1.0,), '15.4.7 config-0-settings.srl:1455'),  # spec 15.4.7 config-0-settings.srl:1455
            ('put', 'u32', (12,), '15.4.7 config-0-settings.srl:1456'),  # spec 15.4.7 config-0-settings.srl:1456
            ('rep', 20, 0, '15.4.7 config-0-settings.srl:1457'),  # spec 15.4.7 config-0-settings.srl:1457
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1458'),  # spec 15.4.7 config-0-settings.srl:1458
            ('rep', 16, 0, '15.4.7 config-0-settings.srl:1459'),  # spec 15.4.7 config-0-settings.srl:1459
            ('put', 'f64', (1.0,), '15.4.7 config-0-settings.srl:1460'),  # spec 15.4.7 config-0-settings.srl:1460
            ('put', 'u32', (400,), '15.4.7 config-0-settings.srl:1461'),  # spec 15.4.7 config-0-settings.srl:1461
            ('rep', 12, 0, '15.4.7 config-0-settings.srl:1462'),  # spec 15.4.7 config-0-settings.srl:1462
            ('put', 'u32', (1,), '15.4.7 config-0-settings.srl:1463'),  # spec 15.4.7 config-0-settings.srl:1463
            ('put', 'cstr', ('Plate,',), '15.4.7 config-0-settings.srl:1464'),  # spec 15.4.7 config-0-settings.srl:1464
            ('put', 'cstr', ('',), '15.4.7 config-0-settings.srl:1465'),  # spec 15.4.7 config-0-settings.srl:1465
            ('put', 'cstr', ('x',), '15.4.7 config-0-settings.srl:1466'),  # spec 15.4.7 config-0-settings.srl:1466
            ('put', 'cstr', ('x',), '15.4.7 config-0-settings.srl:1467'),  # spec 15.4.7 config-0-settings.srl:1467
            ('put', 'u32', (2, 3, 1, 1), '15.4.7 config-0-settings.srl:1468'),  # spec 15.4.7 config-0-settings.srl:1468
            ('put', 'cstr', ('Sheet',), '15.4.7 config-0-settings.srl:1469'),  # spec 15.4.7 config-0-settings.srl:1469
            ('put', 'u32', (0, 1, 1, 0), '15.4.7 config-0-settings.srl:1470'),  # spec 15.4.7 config-0-settings.srl:1470
            ('put', 'cstr', ('%Description%, %MATERIAL%, %LENGTH%, %ANGLE1%, %ANGLE2%, %Angle Direction%, %Angle Rotation%',), '15.4.7 config-0-settings.srl:1471'),  # spec 15.4.7 config-0-settings.srl:1471
            ('put', 'cstr', ('%Description%, %MATERIAL%, %Bounding Box Length%, %Bounding Box Width%, %Sheet Metal Thickness%, %Bounding Box Area%, %Bends%, %Bend Radius%',), '15.4.7 config-0-settings.srl:1472'),  # spec 15.4.7 config-0-settings.srl:1472
            ('put', 'cstr', ('%Description%, %MATERIAL%',), '15.4.7 config-0-settings.srl:1473'),  # spec 15.4.7 config-0-settings.srl:1473
            ('put', 'u32', (1, 0, 1), '15.4.7 config-0-settings.srl:1474'),  # spec 15.4.7 config-0-settings.srl:1474
            ('rep', 6, 0, '15.4.7 config-0-settings.srl:1475'),  # spec 15.4.7 config-0-settings.srl:1475
            ('class', 'moEnvFolder_c', 1, 'env_folder', '15.4.8 config-0-lights.srl:3'),  # spec 15.4.8 config-0-lights.srl:3
            ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
            ('put', 'cstr', ('Lights and Cameras',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
            ('put', 'u32', (0, 1073741824, 6, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (4,), '15.4.8 config-0-lights.srl:5'),  # spec 15.4.8 config-0-lights.srl:5
            ('class', 'moAmbientLight_c', 1, None, '15.4.8 config-0-lights.srl:6'),  # spec 15.4.8 config-0-lights.srl:6
            ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
            ('put', 'cstr', ('Ambient',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
            ('put', 'u32', (0, 3221225472, 12, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.8 config-0-lights.srl:8'),  # spec 15.4.8 config-0-lights.srl:8
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '0x1da7f0beaae8d3c//4294967296'), ('=', '0x1da7f0beaae8d3c%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:10'),  # spec 15.4.8 config-0-lights.srl:10
            ('put', 'f64', (0.3,), '15.4.8 config-0-lights.srl:11'),  # spec 15.4.8 config-0-lights.srl:11
            ('rep', 16, 0, '15.4.8 config-0-lights.srl:12'),  # spec 15.4.8 config-0-lights.srl:12
            ('put', 'u32', (16777215, 0, 1, 0, 1), '15.4.8 config-0-lights.srl:13'),  # spec 15.4.8 config-0-lights.srl:13
            ('put', 'cstr', ('Ambient-1',), '15.4.8 config-0-lights.srl:14'),  # spec 15.4.8 config-0-lights.srl:14
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:15'),  # spec 15.4.8 config-0-lights.srl:15
            ('put', 'f64', (1.0,), '15.4.8 config-0-lights.srl:16'),  # spec 15.4.8 config-0-lights.srl:16
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:17'),  # spec 15.4.8 config-0-lights.srl:17
            ('put', 'f32', (2.75,), '15.4.8 config-0-lights.srl:18'),  # spec 15.4.8 config-0-lights.srl:18
            ('put', 'u32', (0,), '15.4.8 config-0-lights.srl:19'),  # spec 15.4.8 config-0-lights.srl:19
            ('class', 'moDirectionLight_c', 1, None, '15.4.8 config-0-lights.srl:20'),  # spec 15.4.8 config-0-lights.srl:20
            ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
            ('put', 'cstr', ('Directional1',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
            ('put', 'u32', (0, 3221225472, 13, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.8 config-0-lights.srl:22'),  # spec 15.4.8 config-0-lights.srl:22
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '0x1da7f0beaae8d3c//4294967296'), ('=', '0x1da7f0beaae8d3c%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:24'),  # spec 15.4.8 config-0-lights.srl:24
            ('put', 'f64', (0.1, 0.3, 0.3), '15.4.8 config-0-lights.srl:25'),  # spec 15.4.8 config-0-lights.srl:25
            ('put', 'u32', (16777215, 0, 1, 0, 1), '15.4.8 config-0-lights.srl:26'),  # spec 15.4.8 config-0-lights.srl:26
            ('put', 'cstr', ('Directional-1',), '15.4.8 config-0-lights.srl:27'),  # spec 15.4.8 config-0-lights.srl:27
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:28'),  # spec 15.4.8 config-0-lights.srl:28
            ('put', 'f64', (1.0,), '15.4.8 config-0-lights.srl:29'),  # spec 15.4.8 config-0-lights.srl:29
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:30'),  # spec 15.4.8 config-0-lights.srl:30
            ('put', 'f32', (2.75,), '15.4.8 config-0-lights.srl:31'),  # spec 15.4.8 config-0-lights.srl:31
            ('put', 'u32', (0,), '15.4.8 config-0-lights.srl:32'),  # spec 15.4.8 config-0-lights.srl:32
            ('put', 'f64', (7.1, 7.1), '15.4.8 config-0-lights.srl:33'),  # spec 15.4.8 config-0-lights.srl:33
            ('rep', 16, 0, '15.4.8 config-0-lights.srl:34'),  # spec 15.4.8 config-0-lights.srl:34
            ('class', 'moDirectionLight_c', 1, None, '15.4.8 config-0-lights.srl:35'),  # spec 15.4.8 config-0-lights.srl:35
            ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
            ('put', 'cstr', ('Directional2',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
            ('put', 'u32', (0, 3221225472, 14, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.8 config-0-lights.srl:37'),  # spec 15.4.8 config-0-lights.srl:37
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '0x1da7f0beaae8d3c//4294967296'), ('=', '0x1da7f0beaae8d3c%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1,), '15.4.8 config-0-lights.srl:39'),  # spec 15.4.8 config-0-lights.srl:39
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:40'),  # spec 15.4.8 config-0-lights.srl:40
            ('put', 'f64', (0.1, 0.3), '15.4.8 config-0-lights.srl:41'),  # spec 15.4.8 config-0-lights.srl:41
            ('put', 'u32', (16777215, 0, 1, 0, 1), '15.4.8 config-0-lights.srl:42'),  # spec 15.4.8 config-0-lights.srl:42
            ('put', 'cstr', ('Directional-1',), '15.4.8 config-0-lights.srl:43'),  # spec 15.4.8 config-0-lights.srl:43
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:44'),  # spec 15.4.8 config-0-lights.srl:44
            ('put', 'f64', (1.0,), '15.4.8 config-0-lights.srl:45'),  # spec 15.4.8 config-0-lights.srl:45
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:46'),  # spec 15.4.8 config-0-lights.srl:46
            ('put', 'f32', (2.75,), '15.4.8 config-0-lights.srl:47'),  # spec 15.4.8 config-0-lights.srl:47
            ('put', 'u32', (0,), '15.4.8 config-0-lights.srl:48'),  # spec 15.4.8 config-0-lights.srl:48
            ('put', 'f64', (-3.4, 6.1, -7.1), '15.4.8 config-0-lights.srl:49'),  # spec 15.4.8 config-0-lights.srl:49
            ('put', 'u32', (0, 0), '15.4.8 config-0-lights.srl:50'),  # spec 15.4.8 config-0-lights.srl:50
            ('class', 'moDirectionLight_c', 1, None, '15.4.8 config-0-lights.srl:51'),  # spec 15.4.8 config-0-lights.srl:51
            ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
            ('put', 'cstr', ('Directional3',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
            ('put', 'u32', (0, 3221225472, 15, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.8 config-0-lights.srl:53'),  # spec 15.4.8 config-0-lights.srl:53
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '0x1da7f0beaae8d3c//4294967296'), ('=', '0x1da7f0beaae8d3c%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1,), '15.4.8 config-0-lights.srl:55'),  # spec 15.4.8 config-0-lights.srl:55
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:56'),  # spec 15.4.8 config-0-lights.srl:56
            ('put', 'f64', (0.2, 0.3), '15.4.8 config-0-lights.srl:57'),  # spec 15.4.8 config-0-lights.srl:57
            ('put', 'u32', (16777215, 0, 1, 0, 1), '15.4.8 config-0-lights.srl:58'),  # spec 15.4.8 config-0-lights.srl:58
            ('put', 'cstr', ('Directional-1',), '15.4.8 config-0-lights.srl:59'),  # spec 15.4.8 config-0-lights.srl:59
            ('rep', 12, 0, '15.4.8 config-0-lights.srl:60'),  # spec 15.4.8 config-0-lights.srl:60
            ('put', 'f64', (1.0,), '15.4.8 config-0-lights.srl:61'),  # spec 15.4.8 config-0-lights.srl:61
            ('put', 'u32', (1, 0), '15.4.8 config-0-lights.srl:62'),  # spec 15.4.8 config-0-lights.srl:62
            ('put', 'f32', (2.75,), '15.4.8 config-0-lights.srl:63'),  # spec 15.4.8 config-0-lights.srl:63
            ('put', 'u32', (0,), '15.4.8 config-0-lights.srl:64'),  # spec 15.4.8 config-0-lights.srl:64
            ('put', 'f64', (-9.2, 3.4, -1.8), '15.4.8 config-0-lights.srl:65'),  # spec 15.4.8 config-0-lights.srl:65
            ('put', 'u32', (0, 0), '15.4.8 config-0-lights.srl:66'),  # spec 15.4.8 config-0-lights.srl:66
            ('if', ('$', 'model.solid'), (  # spec 15.4.8 config-0-lights.srl:68
                ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
                ('put', 'u32', (('=', '$fixed.id_base+8'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
                ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
                ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
                ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
                ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
                ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
                ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
                ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
                ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
                ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
                ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
                ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
                ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
                ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
                ('put', 'u32', (('=', '$fixed.lights.time//4294967296'), ('=', '$fixed.lights.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
                ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
                ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ), (  # spec 15.4.8 config-0-lights.srl:68
                ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
                ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
                ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
                ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
                ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
                ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
                ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
                ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
                ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
                ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
                ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
                ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
                ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
                ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
                ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
                ('put', 'u32', (('=', '$fixed.lights.time//4294967296'), ('=', '$fixed.lights.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
                ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
                ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ), '15.4.8 config-0-lights.srl:68'),  # spec 15.4.8 config-0-lights.srl:68
            ('put', 'u32', (1, 1), '15.4.8 config-0-lights.srl:73'),  # spec 15.4.8 config-0-lights.srl:73
            ('rep', 6, 0, '15.4.8 config-0-lights.srl:74'),  # spec 15.4.8 config-0-lights.srl:74
            ('class', 'suObList', 1, None, '15.4.8 config-0-views.srl:4'),  # spec 15.4.8 config-0-views.srl:4
            ('rep', 2, 0, '15.4.8 config-0-views.srl:5'),  # spec 15.4.8 config-0-views.srl:5
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:6'),  # spec 15.4.8 config-0-views.srl:6
            ('put', 'cstr', ('*Normal To',), '15.4.8 config-0-views.srl:7'),  # spec 15.4.8 config-0-views.srl:7
            ('rep', 25, 0, '15.4.8 config-0-views.srl:8'),  # spec 15.4.8 config-0-views.srl:8
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:9'),  # spec 15.4.8 config-0-views.srl:9
            ('rep', 26, 0, '15.4.8 config-0-views.srl:10'),  # spec 15.4.8 config-0-views.srl:10
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:11'),  # spec 15.4.8 config-0-views.srl:11
            ('rep', 3, 0, '15.4.8 config-0-views.srl:12'),  # spec 15.4.8 config-0-views.srl:12
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:13'),  # spec 15.4.8 config-0-views.srl:13
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:14'),  # spec 15.4.8 config-0-views.srl:14
            ('rep', 40, 0, '15.4.8 config-0-views.srl:15'),  # spec 15.4.8 config-0-views.srl:15
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:16'),  # spec 15.4.8 config-0-views.srl:16
            ('put', 'cstr', ('*Front',), '15.4.8 config-0-views.srl:17'),  # spec 15.4.8 config-0-views.srl:17
            ('rep', 25, 0, '15.4.8 config-0-views.srl:18'),  # spec 15.4.8 config-0-views.srl:18
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:19'),  # spec 15.4.8 config-0-views.srl:19
            ('rep', 26, 0, '15.4.8 config-0-views.srl:20'),  # spec 15.4.8 config-0-views.srl:20
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:21'),  # spec 15.4.8 config-0-views.srl:21
            ('rep', 3, 0, '15.4.8 config-0-views.srl:22'),  # spec 15.4.8 config-0-views.srl:22
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:23'),  # spec 15.4.8 config-0-views.srl:23
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:24'),  # spec 15.4.8 config-0-views.srl:24
            ('put', 'u32', (0, 1), '15.4.8 config-0-views.srl:25'),  # spec 15.4.8 config-0-views.srl:25
            ('rep', 32, 0, '15.4.8 config-0-views.srl:26'),  # spec 15.4.8 config-0-views.srl:26
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:27'),  # spec 15.4.8 config-0-views.srl:27
            ('put', 'cstr', ('*Back',), '15.4.8 config-0-views.srl:28'),  # spec 15.4.8 config-0-views.srl:28
            ('put', 'u32', (1,), '15.4.8 config-0-views.srl:29'),  # spec 15.4.8 config-0-views.srl:29
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:30'),  # spec 15.4.8 config-0-views.srl:30
            ('put', 'f32', (-1.875,), '15.4.8 config-0-views.srl:31'),  # spec 15.4.8 config-0-views.srl:31
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:32'),  # spec 15.4.8 config-0-views.srl:32
            ('put', 'f64', (6.982962677686267e-15,), '15.4.8 config-0-views.srl:33'),  # spec 15.4.8 config-0-views.srl:33
            ('rep', 7, 0, '15.4.8 config-0-views.srl:34'),  # spec 15.4.8 config-0-views.srl:34
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:35'),  # spec 15.4.8 config-0-views.srl:35
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:36'),  # spec 15.4.8 config-0-views.srl:36
            ('put', 'f32', (1.875,), '15.4.8 config-0-views.srl:37'),  # spec 15.4.8 config-0-views.srl:37
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:38'),  # spec 15.4.8 config-0-views.srl:38
            ('put', 'f64', (-6.982962677686267e-15,), '15.4.8 config-0-views.srl:39'),  # spec 15.4.8 config-0-views.srl:39
            ('rep', 7, 0, '15.4.8 config-0-views.srl:40'),  # spec 15.4.8 config-0-views.srl:40
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:41'),  # spec 15.4.8 config-0-views.srl:41
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:42'),  # spec 15.4.8 config-0-views.srl:42
            ('put', 'f32', (-1.875,), '15.4.8 config-0-views.srl:43'),  # spec 15.4.8 config-0-views.srl:43
            ('rep', 24, 0, '15.4.8 config-0-views.srl:44'),  # spec 15.4.8 config-0-views.srl:44
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:45'),  # spec 15.4.8 config-0-views.srl:45
            ('rep', 26, 0, '15.4.8 config-0-views.srl:46'),  # spec 15.4.8 config-0-views.srl:46
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:47'),  # spec 15.4.8 config-0-views.srl:47
            ('rep', 3, 0, '15.4.8 config-0-views.srl:48'),  # spec 15.4.8 config-0-views.srl:48
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:49'),  # spec 15.4.8 config-0-views.srl:49
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:50'),  # spec 15.4.8 config-0-views.srl:50
            ('put', 'u32', (0, 2), '15.4.8 config-0-views.srl:51'),  # spec 15.4.8 config-0-views.srl:51
            ('rep', 32, 0, '15.4.8 config-0-views.srl:52'),  # spec 15.4.8 config-0-views.srl:52
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:53'),  # spec 15.4.8 config-0-views.srl:53
            ('put', 'cstr', ('*Left',), '15.4.8 config-0-views.srl:54'),  # spec 15.4.8 config-0-views.srl:54
            ('put', 'i32', (-511,), '15.4.8 config-0-views.srl:55'),  # spec 15.4.8 config-0-views.srl:55
            ('hex', 'FFFF', '15.4.8 config-0-views.srl:56'),  # spec 15.4.8 config-0-views.srl:56
            ('put', 'u32', (12382207,), '15.4.8 config-0-views.srl:57'),  # spec 15.4.8 config-0-views.srl:57
            ('rep', 6, 0, '15.4.8 config-0-views.srl:58'),  # spec 15.4.8 config-0-views.srl:58
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:59'),  # spec 15.4.8 config-0-views.srl:59
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:60'),  # spec 15.4.8 config-0-views.srl:60
            ('put', 'f32', (-1.875,), '15.4.8 config-0-views.srl:61'),  # spec 15.4.8 config-0-views.srl:61
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:62'),  # spec 15.4.8 config-0-views.srl:62
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:63'),  # spec 15.4.8 config-0-views.srl:63
            ('rep', 7, 0, '15.4.8 config-0-views.srl:64'),  # spec 15.4.8 config-0-views.srl:64
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:65'),  # spec 15.4.8 config-0-views.srl:65
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:66'),  # spec 15.4.8 config-0-views.srl:66
            ('put', 'f32', (1.875,), '15.4.8 config-0-views.srl:67'),  # spec 15.4.8 config-0-views.srl:67
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:68'),  # spec 15.4.8 config-0-views.srl:68
            ('put', 'f64', (-3.5527136788005e-15,), '15.4.8 config-0-views.srl:69'),  # spec 15.4.8 config-0-views.srl:69
            ('rep', 24, 0, '15.4.8 config-0-views.srl:70'),  # spec 15.4.8 config-0-views.srl:70
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:71'),  # spec 15.4.8 config-0-views.srl:71
            ('rep', 26, 0, '15.4.8 config-0-views.srl:72'),  # spec 15.4.8 config-0-views.srl:72
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:73'),  # spec 15.4.8 config-0-views.srl:73
            ('rep', 3, 0, '15.4.8 config-0-views.srl:74'),  # spec 15.4.8 config-0-views.srl:74
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:75'),  # spec 15.4.8 config-0-views.srl:75
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:76'),  # spec 15.4.8 config-0-views.srl:76
            ('put', 'u32', (0, 3), '15.4.8 config-0-views.srl:77'),  # spec 15.4.8 config-0-views.srl:77
            ('rep', 32, 0, '15.4.8 config-0-views.srl:78'),  # spec 15.4.8 config-0-views.srl:78
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:79'),  # spec 15.4.8 config-0-views.srl:79
            ('put', 'cstr', ('*Right',), '15.4.8 config-0-views.srl:80'),  # spec 15.4.8 config-0-views.srl:80
            ('put', 'i32', (-511,), '15.4.8 config-0-views.srl:81'),  # spec 15.4.8 config-0-views.srl:81
            ('hex', 'FFFF', '15.4.8 config-0-views.srl:82'),  # spec 15.4.8 config-0-views.srl:82
            ('put', 'u32', (12382207,), '15.4.8 config-0-views.srl:83'),  # spec 15.4.8 config-0-views.srl:83
            ('rep', 7, 0, '15.4.8 config-0-views.srl:84'),  # spec 15.4.8 config-0-views.srl:84
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:85'),  # spec 15.4.8 config-0-views.srl:85
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:86'),  # spec 15.4.8 config-0-views.srl:86
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:87'),  # spec 15.4.8 config-0-views.srl:87
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:88'),  # spec 15.4.8 config-0-views.srl:88
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:89'),  # spec 15.4.8 config-0-views.srl:89
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:90'),  # spec 15.4.8 config-0-views.srl:90
            ('put', 'f64', (-3.5527136788005e-15,), '15.4.8 config-0-views.srl:91'),  # spec 15.4.8 config-0-views.srl:91
            ('rep', 24, 0, '15.4.8 config-0-views.srl:92'),  # spec 15.4.8 config-0-views.srl:92
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:93'),  # spec 15.4.8 config-0-views.srl:93
            ('rep', 26, 0, '15.4.8 config-0-views.srl:94'),  # spec 15.4.8 config-0-views.srl:94
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:95'),  # spec 15.4.8 config-0-views.srl:95
            ('rep', 3, 0, '15.4.8 config-0-views.srl:96'),  # spec 15.4.8 config-0-views.srl:96
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:97'),  # spec 15.4.8 config-0-views.srl:97
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:98'),  # spec 15.4.8 config-0-views.srl:98
            ('put', 'u32', (0, 4), '15.4.8 config-0-views.srl:99'),  # spec 15.4.8 config-0-views.srl:99
            ('rep', 32, 0, '15.4.8 config-0-views.srl:100'),  # spec 15.4.8 config-0-views.srl:100
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:101'),  # spec 15.4.8 config-0-views.srl:101
            ('put', 'cstr', ('*Top',), '15.4.8 config-0-views.srl:102'),  # spec 15.4.8 config-0-views.srl:102
            ('put', 'u32', (1,), '15.4.8 config-0-views.srl:103'),  # spec 15.4.8 config-0-views.srl:103
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:104'),  # spec 15.4.8 config-0-views.srl:104
            ('put', 'f32', (1.875,), '15.4.8 config-0-views.srl:105'),  # spec 15.4.8 config-0-views.srl:105
            ('rep', 7, 0, '15.4.8 config-0-views.srl:106'),  # spec 15.4.8 config-0-views.srl:106
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:107'),  # spec 15.4.8 config-0-views.srl:107
            ('rep', 13, 0, '15.4.8 config-0-views.srl:108'),  # spec 15.4.8 config-0-views.srl:108
            ('put', 'f64', (-3.5527136788005e-15, 1.0), '15.4.8 config-0-views.srl:109'),  # spec 15.4.8 config-0-views.srl:109
            ('rep', 7, 0, '15.4.8 config-0-views.srl:110'),  # spec 15.4.8 config-0-views.srl:110
            ('put', 'u32', (128,), '15.4.8 config-0-views.srl:111'),  # spec 15.4.8 config-0-views.srl:111
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:112'),  # spec 15.4.8 config-0-views.srl:112
            ('put', 'f32', (-1.875,), '15.4.8 config-0-views.srl:113'),  # spec 15.4.8 config-0-views.srl:113
            ('put', 'f64', (-3.5527136788005e-15,), '15.4.8 config-0-views.srl:114'),  # spec 15.4.8 config-0-views.srl:114
            ('rep', 24, 0, '15.4.8 config-0-views.srl:115'),  # spec 15.4.8 config-0-views.srl:115
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:116'),  # spec 15.4.8 config-0-views.srl:116
            ('rep', 26, 0, '15.4.8 config-0-views.srl:117'),  # spec 15.4.8 config-0-views.srl:117
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:118'),  # spec 15.4.8 config-0-views.srl:118
            ('rep', 3, 0, '15.4.8 config-0-views.srl:119'),  # spec 15.4.8 config-0-views.srl:119
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:120'),  # spec 15.4.8 config-0-views.srl:120
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:121'),  # spec 15.4.8 config-0-views.srl:121
            ('put', 'u32', (0, 5), '15.4.8 config-0-views.srl:122'),  # spec 15.4.8 config-0-views.srl:122
            ('rep', 32, 0, '15.4.8 config-0-views.srl:123'),  # spec 15.4.8 config-0-views.srl:123
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:124'),  # spec 15.4.8 config-0-views.srl:124
            ('put', 'cstr', ('*Bottom',), '15.4.8 config-0-views.srl:125'),  # spec 15.4.8 config-0-views.srl:125
            ('put', 'u32', (1,), '15.4.8 config-0-views.srl:126'),  # spec 15.4.8 config-0-views.srl:126
            ('put', 'u8', (0,), '15.4.8 config-0-views.srl:127'),  # spec 15.4.8 config-0-views.srl:127
            ('put', 'f32', (1.875,), '15.4.8 config-0-views.srl:128'),  # spec 15.4.8 config-0-views.srl:128
            ('rep', 24, 0, '15.4.8 config-0-views.srl:129'),  # spec 15.4.8 config-0-views.srl:129
            ('put', 'f64', (-3.5527136788005e-15, -1.0), '15.4.8 config-0-views.srl:130'),  # spec 15.4.8 config-0-views.srl:130
            ('put', 'u32', (0, 0), '15.4.8 config-0-views.srl:131'),  # spec 15.4.8 config-0-views.srl:131
            ('put', 'f64', (1.0, -3.5527136788005e-15), '15.4.8 config-0-views.srl:132'),  # spec 15.4.8 config-0-views.srl:132
            ('rep', 24, 0, '15.4.8 config-0-views.srl:133'),  # spec 15.4.8 config-0-views.srl:133
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:134'),  # spec 15.4.8 config-0-views.srl:134
            ('rep', 26, 0, '15.4.8 config-0-views.srl:135'),  # spec 15.4.8 config-0-views.srl:135
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:136'),  # spec 15.4.8 config-0-views.srl:136
            ('rep', 3, 0, '15.4.8 config-0-views.srl:137'),  # spec 15.4.8 config-0-views.srl:137
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:138'),  # spec 15.4.8 config-0-views.srl:138
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:139'),  # spec 15.4.8 config-0-views.srl:139
            ('put', 'u32', (0, 6), '15.4.8 config-0-views.srl:140'),  # spec 15.4.8 config-0-views.srl:140
            ('rep', 32, 0, '15.4.8 config-0-views.srl:141'),  # spec 15.4.8 config-0-views.srl:141
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:142'),  # spec 15.4.8 config-0-views.srl:142
            ('put', 'cstr', ('*Isometric',), '15.4.8 config-0-views.srl:143'),  # spec 15.4.8 config-0-views.srl:143
            ('hex', '01', '15.4.8 config-0-views.srl:144'),  # spec 15.4.8 config-0-views.srl:144
            ('put', 'f64', (0.7071067811865464, -0.4082040559113551, 0.5773815451999837), '15.4.8 config-0-views.srl:145'),  # spec 15.4.8 config-0-views.srl:145
            ('put', 'u32', (0,), '15.4.8 config-0-views.srl:146'),  # spec 15.4.8 config-0-views.srl:146
            ('put', 'f32', (0.015625,), '15.4.8 config-0-views.srl:147'),  # spec 15.4.8 config-0-views.srl:147
            ('put', 'f64', (0.8165408118857499, 0.5772877120855426, -0.7071067811865488, -0.4082040559113538, 0.5773815451999819), '15.4.8 config-0-views.srl:148'),  # spec 15.4.8 config-0-views.srl:148
            ('rep', 24, 0, '15.4.8 config-0-views.srl:149'),  # spec 15.4.8 config-0-views.srl:149
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:150'),  # spec 15.4.8 config-0-views.srl:150
            ('rep', 26, 0, '15.4.8 config-0-views.srl:151'),  # spec 15.4.8 config-0-views.srl:151
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:152'),  # spec 15.4.8 config-0-views.srl:152
            ('rep', 3, 0, '15.4.8 config-0-views.srl:153'),  # spec 15.4.8 config-0-views.srl:153
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:154'),  # spec 15.4.8 config-0-views.srl:154
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:155'),  # spec 15.4.8 config-0-views.srl:155
            ('put', 'u32', (0, 7), '15.4.8 config-0-views.srl:156'),  # spec 15.4.8 config-0-views.srl:156
            ('rep', 32, 0, '15.4.8 config-0-views.srl:157'),  # spec 15.4.8 config-0-views.srl:157
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:158'),  # spec 15.4.8 config-0-views.srl:158
            ('put', 'cstr', ('*Trimetric',), '15.4.8 config-0-views.srl:159'),  # spec 15.4.8 config-0-views.srl:159
            ('hex', '01', '15.4.8 config-0-views.srl:160'),  # spec 15.4.8 config-0-views.srl:160
            ('put', 'f64', (0.8844181216774213, -0.24036589468392133, 0.400036026779314), '15.4.8 config-0-views.srl:161'),  # spec 15.4.8 config-0-views.srl:161
            ('rep', 6, 0, '15.4.8 config-0-views.srl:162'),  # spec 15.4.8 config-0-views.srl:162
            ('hex', '703C', '15.4.8 config-0-views.srl:163'),  # spec 15.4.8 config-0-views.srl:163
            ('put', 'f64', (0.8571673007021341, 0.5150380749100181, -0.4666953889300622, -0.4555090068042732, 0.7580942940502868), '15.4.8 config-0-views.srl:164'),  # spec 15.4.8 config-0-views.srl:164
            ('rep', 24, 0, '15.4.8 config-0-views.srl:165'),  # spec 15.4.8 config-0-views.srl:165
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:166'),  # spec 15.4.8 config-0-views.srl:166
            ('rep', 26, 0, '15.4.8 config-0-views.srl:167'),  # spec 15.4.8 config-0-views.srl:167
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:168'),  # spec 15.4.8 config-0-views.srl:168
            ('rep', 3, 0, '15.4.8 config-0-views.srl:169'),  # spec 15.4.8 config-0-views.srl:169
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:170'),  # spec 15.4.8 config-0-views.srl:170
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:171'),  # spec 15.4.8 config-0-views.srl:171
            ('put', 'u32', (0, 8), '15.4.8 config-0-views.srl:172'),  # spec 15.4.8 config-0-views.srl:172
            ('rep', 32, 0, '15.4.8 config-0-views.srl:173'),  # spec 15.4.8 config-0-views.srl:173
            ('class', 'moView_c', 1, None, '15.4.8 config-0-views.srl:174'),  # spec 15.4.8 config-0-views.srl:174
            ('put', 'cstr', ('*Dimetric',), '15.4.8 config-0-views.srl:175'),  # spec 15.4.8 config-0-views.srl:175
            ('hex', '01', '15.4.8 config-0-views.srl:176'),  # spec 15.4.8 config-0-views.srl:176
            ('put', 'f64', (0.9354143467241411, -0.11785113014268137, 0.33333333326677816), '15.4.8 config-0-views.srl:177'),  # spec 15.4.8 config-0-views.srl:177
            ('rep', 6, 0, '15.4.8 config-0-views.srl:178'),  # spec 15.4.8 config-0-views.srl:178
            ('hex', '603C', '15.4.8 config-0-views.srl:179'),  # spec 15.4.8 config-0-views.srl:179
            ('put', 'f64', (0.942809041610104, 0.33333333325402237, -0.35355339051216605, -0.31180478216719176, 0.8819171037433291), '15.4.8 config-0-views.srl:180'),  # spec 15.4.8 config-0-views.srl:180
            ('rep', 24, 0, '15.4.8 config-0-views.srl:181'),  # spec 15.4.8 config-0-views.srl:181
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:182'),  # spec 15.4.8 config-0-views.srl:182
            ('rep', 26, 0, '15.4.8 config-0-views.srl:183'),  # spec 15.4.8 config-0-views.srl:183
            ('put', 'f64', (1.0,), '15.4.8 config-0-views.srl:184'),  # spec 15.4.8 config-0-views.srl:184
            ('rep', 3, 0, '15.4.8 config-0-views.srl:185'),  # spec 15.4.8 config-0-views.srl:185
            ('put', 'i32', (-1,), '15.4.8 config-0-views.srl:186'),  # spec 15.4.8 config-0-views.srl:186
            ('put', 'f64', (-1.0,), '15.4.8 config-0-views.srl:187'),  # spec 15.4.8 config-0-views.srl:187
            ('put', 'u32', (0, 9), '15.4.8 config-0-views.srl:188'),  # spec 15.4.8 config-0-views.srl:188
            ('rep', 33, 0, '15.4.8 config-0-views.srl:189'),  # spec 15.4.8 config-0-views.srl:189
            ('put', 'u32', (50, 108), '15.4.8 config-0-views.srl:190'),  # spec 15.4.8 config-0-views.srl:190
            ('class', 'moFeatColorTab_c', 0, None, '15.4.9 config-0.srl:265'),  # spec 15.4.9 config-0.srl:265
            ('rep', 6, 0, '15.4.9 config-0.srl:266'),  # spec 15.4.9 config-0.srl:266
            ('put', 'u32', (10, 0, 0), '15.4.9 config-0.srl:267'),  # spec 15.4.9 config-0.srl:267
            ('class', 'moSketchBlockMgr_c', 1, 'sketch_blocks', '15.4.9 config-0.srl:268'),  # spec 15.4.9 config-0.srl:268
            ('rep', 2, 0, '15.4.9 config-0.srl:269'),  # spec 15.4.9 config-0.srl:269
            ('put', 'u32', (0, 1073741824, 4294967295, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.9 config-0.srl:271'),  # spec 15.4.9 config-0.srl:271
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$config0.sketch_blocks_time//4294967296'), ('=', '$config0.sketch_blocks_time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1,), '15.4.9 config-0.srl:273'),  # spec 15.4.9 config-0.srl:273
            ('hex', '690CB15972524B4BA83A09510F', '15.4.9 config-0.srl:274'),  # spec 15.4.9 config-0.srl:274
            ('put', 'u32', (13113814,), '15.4.9 config-0.srl:275'),  # spec 15.4.9 config-0.srl:275
            ('rep', 3, 0, '15.4.9 config-0.srl:276'),  # spec 15.4.9 config-0.srl:276
            ('objref', 'sketch_blocks', '15.4.9 config-0.srl:277'),  # spec 15.4.9 config-0.srl:277
            ('put', 'u32', (0, 0), '15.4.9 config-0.srl:278'),  # spec 15.4.9 config-0.srl:278
            ('class', 'suObList', 1, None, '15.4.9 config-0.srl:280'),  # spec 15.4.9 config-0.srl:280
            ('put', 'u16', (('=', 'int($model.solid)'),), '15.4.9 config-0.srl:281'),  # spec 15.4.9 config-0.srl:281
            ('if', ('$', 'model.solid'), (  # spec 15.4.9 config-0.srl:282
                ('class', 'moAnnotationView_c', 1, None, '15.4.9 config-0.srl:283'),  # spec 15.4.9 config-0.srl:283
                ('put', 'cstr', ('*Top',), '15.4.9 config-0.srl:284'),  # spec 15.4.9 config-0.srl:284
                ('put', 'u32', (1,), '15.4.9 config-0.srl:285'),  # spec 15.4.9 config-0.srl:285
                ('put', 'u8', (0,), '15.4.9 config-0.srl:286'),  # spec 15.4.9 config-0.srl:286
                ('put', 'f32', (1.875,), '15.4.9 config-0.srl:287'),  # spec 15.4.9 config-0.srl:287
                ('rep', 32, 0, '15.4.9 config-0.srl:288'),  # spec 15.4.9 config-0.srl:288
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:289'),  # spec 15.4.9 config-0.srl:289
                ('rep', 7, 0, '15.4.9 config-0.srl:290'),  # spec 15.4.9 config-0.srl:290
                ('put', 'u32', (128,), '15.4.9 config-0.srl:291'),  # spec 15.4.9 config-0.srl:291
                ('put', 'u8', (0,), '15.4.9 config-0.srl:292'),  # spec 15.4.9 config-0.srl:292
                ('put', 'f32', (-1.875,), '15.4.9 config-0.srl:293'),  # spec 15.4.9 config-0.srl:293
                ('rep', 7, 0, '15.4.9 config-0.srl:294'),  # spec 15.4.9 config-0.srl:294
                ('put', 'u32', (128,), '15.4.9 config-0.srl:295'),  # spec 15.4.9 config-0.srl:295
                ('rep', 21, 0, '15.4.9 config-0.srl:296'),  # spec 15.4.9 config-0.srl:296
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:297'),  # spec 15.4.9 config-0.srl:297
                ('rep', 26, 0, '15.4.9 config-0.srl:298'),  # spec 15.4.9 config-0.srl:298
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:299'),  # spec 15.4.9 config-0.srl:299
                ('rep', 3, 0, '15.4.9 config-0.srl:300'),  # spec 15.4.9 config-0.srl:300
                ('put', 'i32', (-1,), '15.4.9 config-0.srl:301'),  # spec 15.4.9 config-0.srl:301
                ('put', 'f64', (-1.0,), '15.4.9 config-0.srl:302'),  # spec 15.4.9 config-0.srl:302
                ('put', 'u32', (0, 200), '15.4.9 config-0.srl:303'),  # spec 15.4.9 config-0.srl:303
                ('rep', 58, 0, '15.4.9 config-0.srl:304'),  # spec 15.4.9 config-0.srl:304
                ('put', 'u32', (1,), '15.4.9 config-0.srl:305'),  # spec 15.4.9 config-0.srl:305
                ('put', 'i32', (-65536,), '15.4.9 config-0.srl:306'),  # spec 15.4.9 config-0.srl:306
                ('put', 'u32', (65535,), '15.4.9 config-0.srl:307'),  # spec 15.4.9 config-0.srl:307
                ('put', 'i32', (-65536, -1), '15.4.9 config-0.srl:308'),  # spec 15.4.9 config-0.srl:308
                ('hex', 'FFFF', '15.4.9 config-0.srl:309'),  # spec 15.4.9 config-0.srl:309
            ), (  # spec 15.4.9 config-0.srl:282
            ), '15.4.9 config-0.srl:282'),  # spec 15.4.9 config-0.srl:282
            ('put', 'u32', (('=', '199+int($model.solid)'), 199, 1, 199), '15.4.9 config-0.srl:311'),  # spec 15.4.9 config-0.srl:311
            ('rep', 30, 0, '15.4.9 config-0.srl:312'),  # spec 15.4.9 config-0.srl:312
            ('if', ('$', 'model.solid'), (  # spec 15.4.9 config-0.srl:313
                ('class', 'moPMarkRecord_c', 1, None, '15.4.9 config-0.srl:314'),  # spec 15.4.9 config-0.srl:314
                ('put', 'u32', (3,), '15.4.9 config-0.srl:315'),  # spec 15.4.9 config-0.srl:315
            ), (  # spec 15.4.9 config-0.srl:313
                ('put', 'u16', (0,), '15.4.9 config-0.srl:317'),  # spec 15.4.9 config-0.srl:317
            ), '15.4.9 config-0.srl:313'),  # spec 15.4.9 config-0.srl:313
            ('put', 'u32', (1,), '15.4.9 config-0.srl:319'),  # spec 15.4.9 config-0.srl:319
            ('rep', 12, 0, '15.4.9 config-0.srl:320'),  # spec 15.4.9 config-0.srl:320
            ('put', 'u32', (20, 0, 20), '15.4.9 config-0.srl:321'),  # spec 15.4.9 config-0.srl:321
            ('rep', 16, 0, '15.4.9 config-0.srl:322'),  # spec 15.4.9 config-0.srl:322
            ('class', 'suObList', 1, None, '15.4.9 config-0.srl:323'),  # spec 15.4.9 config-0.srl:323
            ('rep', 6, 0, '15.4.9 config-0.srl:324'),  # spec 15.4.9 config-0.srl:324
            ('put', 'cstr', ('',), '15.4.9 config-0.srl:325'),  # spec 15.4.9 config-0.srl:325
            ('put', 'cstr', ('',), '15.4.9 config-0.srl:326'),  # spec 15.4.9 config-0.srl:326
            ('class', 'moCThreadRefMgr_c', 1, None, '15.4.9 config-0.srl:327'),  # spec 15.4.9 config-0.srl:327
            ('rep', 23, 0, '15.4.9 config-0.srl:330'),  # spec 15.4.9 config-0.srl:330
            ('if', ('$', 'config0.mass_block'), (  # spec 15.4.9 config-0.srl:331
                ('put', 'u32', (1, 1, ('=', 'len($bodies)')), '15.4.9 config-0.srl:332'),  # spec 15.4.9 config-0.srl:332
                ('for', 'b', ('$', 'bodies'), False, (  # spec 15.4.9 config-0.srl:333
                    ('put', 'u32', (('$', 'b.id'), ('=', '$doc.stamp2-2*(len($bodies)-1-$b_index)')), '15.4.9 config-0.srl:334'),  # spec 15.4.9 config-0.srl:334
                    ('put', 'f64', (1.0,), '15.4.9 config-0.srl:335'),  # spec 15.4.9 config-0.srl:335
                ), '15.4.9 config-0.srl:333'),  # spec 15.4.9 config-0.srl:333
                ('put', 'f64', (('$', 'config0.mass.0'), ('$', 'config0.mass.1'), ('$', 'config0.mass.2')), '15.4.9 config-0.srl:337'),  # spec 15.4.9 config-0.srl:337
                ('put', 'f64', (('$', 'config0.mass.3'), ('$', 'config0.mass.4'), ('$', 'config0.mass.5')), '15.4.9 config-0.srl:338'),  # spec 15.4.9 config-0.srl:338
                ('put', 'f64', (('$', 'config0.mass.6'), ('$', 'config0.mass.7'), ('$', 'config0.mass.8')), '15.4.9 config-0.srl:339'),  # spec 15.4.9 config-0.srl:339
                ('put', 'f64', (('$', 'config0.mass.9'), ('$', 'config0.mass.10'), ('$', 'config0.mass.11')), '15.4.9 config-0.srl:340'),  # spec 15.4.9 config-0.srl:340
                ('put', 'u32', (1,), '15.4.9 config-0.srl:341'),  # spec 15.4.9 config-0.srl:341
                ('rep', 16, 0, '15.4.9 config-0.srl:342'),  # spec 15.4.9 config-0.srl:342
                ('put', 'f64', (0.995,), '15.4.9 config-0.srl:343'),  # spec 15.4.9 config-0.srl:343
                ('rep', 16, 0, '15.4.9 config-0.srl:344'),  # spec 15.4.9 config-0.srl:344
                ('put', 'cstr', ('',), '15.4.9 config-0.srl:345'),  # spec 15.4.9 config-0.srl:345
                ('put', 'cstr', ('',), '15.4.9 config-0.srl:346'),  # spec 15.4.9 config-0.srl:346
                ('rep', 28, 0, '15.4.9 config-0.srl:347'),  # spec 15.4.9 config-0.srl:347
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:348'),  # spec 15.4.9 config-0.srl:348
                ('rep', 24, 0, '15.4.9 config-0.srl:349'),  # spec 15.4.9 config-0.srl:349
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:350'),  # spec 15.4.9 config-0.srl:350
                ('rep', 24, 0, '15.4.9 config-0.srl:351'),  # spec 15.4.9 config-0.srl:351
                ('put', 'f64', (1.0,), '15.4.9 config-0.srl:352'),  # spec 15.4.9 config-0.srl:352
                ('put', 'u32', (1,), '15.4.9 config-0.srl:353'),  # spec 15.4.9 config-0.srl:353
                ('rep', 6, 0, '15.4.9 config-0.srl:354'),  # spec 15.4.9 config-0.srl:354
            ), (  # spec 15.4.9 config-0.srl:331
                ('put', 'u32', (0, 0, 0), '15.4.9 config-0.srl:356'),  # spec 15.4.9 config-0.srl:356
            ), '15.4.9 config-0.srl:331'),  # spec 15.4.9 config-0.srl:331
            ('class', 'moPrtExplViewManager_c', 1, None, '15.4.9 config-0.srl:358'),  # spec 15.4.9 config-0.srl:358
            ('rep', 2, 0, '15.4.9 config-0.srl:359'),  # spec 15.4.9 config-0.srl:359
            ('put', 'u32', (0, 1073741824, 19, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
            ('put', 'u16', (0,), '15.4.9 config-0.srl:361'),  # spec 15.4.9 config-0.srl:361
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '0x0//4294967296'), ('=', '0x0%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
            ('put', 'u32', (1,), '15.4.9 config-0.srl:363'),  # spec 15.4.9 config-0.srl:363
            ('rep', 12, 0, '15.4.9 config-0.srl:364'),  # spec 15.4.9 config-0.srl:364
            ('put', 'i32', (-1, -1), '15.4.9 config-0.srl:365'),  # spec 15.4.9 config-0.srl:365
            ('rep', 2, 0, '15.4.9 config-0.srl:366'),  # spec 15.4.9 config-0.srl:366
            ('put', 'u32', (20, 1), '15.4.9 config-0.srl:367'),  # spec 15.4.9 config-0.srl:367
            ('rep', 16, 0, '15.4.9 config-0.srl:368'),  # spec 15.4.9 config-0.srl:368
            ('put', 'u32', (101, 0, 0), '15.4.9 config-0.srl:369'),  # spec 15.4.9 config-0.srl:369
        ), '15.4.6 config-0.srl:224'),  # spec 15.4.6 config-0.srl:224
    ),  # spec 15.4 config-0.srl
    'Contents/Config-0-LWDATA': (  # spec 15.2 config-0-lwdata.srl
        ('put', 'u32', (('$', 'doc.stamp'),), '15.2.5.1 config-0-lwdata.srl:5'),  # spec 15.2.5.1 config-0-lwdata.srl:5
        ('if', ('$', 'model.solid'), (  # spec 15.2.5.1 config-0-lwdata.srl:7
            ('put', 'f64', (('$', 'model.sphere.0'), ('$', 'model.sphere.1'), ('$', 'model.sphere.2')), '15.2.5.1 config-0-lwdata.srl:8'),  # spec 15.2.5.1 config-0-lwdata.srl:8
            ('put', 'f64', (('$', 'model.max.0'), ('$', 'model.max.1'), ('$', 'model.max.2')), '15.2.5.1 config-0-lwdata.srl:9'),  # spec 15.2.5.1 config-0-lwdata.srl:9
            ('put', 'f64', (('$', 'model.min.0'), ('$', 'model.min.1'), ('$', 'model.min.2')), '15.2.5.1 config-0-lwdata.srl:10'),  # spec 15.2.5.1 config-0-lwdata.srl:10
            ('put', 'f64', (('$', 'model.sphere.3'),), '15.2.5.1 config-0-lwdata.srl:11'),  # spec 15.2.5.1 config-0-lwdata.srl:11
        ), (  # spec 15.2.5.1 config-0-lwdata.srl:7
            ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.1 config-0-lwdata.srl:13'),  # spec 15.2.5.1 config-0-lwdata.srl:13
            ('put', 'f64', (-1.0, -1.0, -1.0), '15.2.5.1 config-0-lwdata.srl:14'),  # spec 15.2.5.1 config-0-lwdata.srl:14
            ('put', 'f64', (1.0, 1.0, 1.0), '15.2.5.1 config-0-lwdata.srl:15'),  # spec 15.2.5.1 config-0-lwdata.srl:15
            ('put', 'f64', (-2.0,), '15.2.5.1 config-0-lwdata.srl:16'),  # spec 15.2.5.1 config-0-lwdata.srl:16
        ), '15.2.5.1 config-0-lwdata.srl:7'),  # spec 15.2.5.1 config-0-lwdata.srl:7
        ('put', 'f64', (1000.0,), '15.2.5.1 config-0-lwdata.srl:18'),  # spec 15.2.5.1 config-0-lwdata.srl:18
        ('archive', 'start', 1, '15.2.5.2 config-0-lwdata.srl:21'),  # spec 15.2.5.2 config-0-lwdata.srl:21
        ('class', 'gcXhatch_c', 1, None, '15.2.5.2 config-0-lwdata.srl:22'),  # spec 15.2.5.2 config-0-lwdata.srl:22
        ('put', 'cstr', ('ANSI31 (Iron BrickStone)',), '15.2.5.2 config-0-lwdata.srl:23'),  # spec 15.2.5.2 config-0-lwdata.srl:23
        ('put', 'f64', (0.0,), '15.2.5.2 config-0-lwdata.srl:24'),  # spec 15.2.5.2 config-0-lwdata.srl:24
        ('put', 'f64', (1.0,), '15.2.5.2 config-0-lwdata.srl:25'),  # spec 15.2.5.2 config-0-lwdata.srl:25
        ('put', 'f64', (0.0,), '15.2.5.2 config-0-lwdata.srl:26'),  # spec 15.2.5.2 config-0-lwdata.srl:26
        ('put', 'u32', (1,), '15.2.5.2 config-0-lwdata.srl:27'),  # spec 15.2.5.2 config-0-lwdata.srl:27
        ('put', 'i32', (-1, -1), '15.2.5.2 config-0-lwdata.srl:28'),  # spec 15.2.5.2 config-0-lwdata.srl:28
        ('put', 'u32', (0,), '15.2.5.2 config-0-lwdata.srl:29'),  # spec 15.2.5.2 config-0-lwdata.srl:29
        ('put', 'u16', (3,), '15.2.5.2 config-0-lwdata.srl:30'),  # spec 15.2.5.2 config-0-lwdata.srl:30
        ('class', 'moLWPlaneNodeData_c', 1, None, '15.2.5.3 config-0-lwdata.srl:50'),  # spec 15.2.5.3 config-0-lwdata.srl:50
        ('put', 'cstr', ('moRefPlane_c',), '15.2.5.3 config-0-lwdata.srl:51'),  # spec 15.2.5.3 config-0-lwdata.srl:51
        ('put', 'cstr', ('Front Plane',), '15.2.5.3 config-0-lwdata.srl:52'),  # spec 15.2.5.3 config-0-lwdata.srl:52
        ('put', 'u32', (2,), '15.2.5.3 config-0-lwdata.srl:53'),  # spec 15.2.5.3 config-0-lwdata.srl:53
        ('put', 'u32', (0, 1), '15.2.5.3 config-0-lwdata.srl:54'),  # spec 15.2.5.3 config-0-lwdata.srl:54
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:55'),  # spec 15.2.5.3 config-0-lwdata.srl:55
        ('put', 'f64', (0.0, 0.0, 1.0), '15.2.5.3 config-0-lwdata.srl:56'),  # spec 15.2.5.3 config-0-lwdata.srl:56
        ('put', 'f64', (('$', 'planes.front.centre.0'), ('$', 'planes.front.centre.1'), ('$', 'planes.front.centre.2')), '15.2.5.3 config-0-lwdata.srl:35'),  # spec 15.2.5.3 config-0-lwdata.srl:35
        ('put', 'f64', (('$', 'planes.front.max.0'), ('$', 'planes.front.max.1'), ('$', 'planes.front.max.2')), '15.2.5.3 config-0-lwdata.srl:36'),  # spec 15.2.5.3 config-0-lwdata.srl:36
        ('put', 'f64', (('$', 'planes.front.min.0'), ('$', 'planes.front.min.1'), ('$', 'planes.front.min.2')), '15.2.5.3 config-0-lwdata.srl:37'),  # spec 15.2.5.3 config-0-lwdata.srl:37
        ('put', 'f64', (('$', 'planes.front.radius'),), '15.2.5.3 config-0-lwdata.srl:38'),  # spec 15.2.5.3 config-0-lwdata.srl:38
        ('put', 'f64', (1.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:58'),  # spec 15.2.5.3 config-0-lwdata.srl:58
        ('put', 'f64', (0.0, 1.0, 0.0), '15.2.5.3 config-0-lwdata.srl:59'),  # spec 15.2.5.3 config-0-lwdata.srl:59
        ('put', 'f64', (0.0, 0.0, 1.0), '15.2.5.3 config-0-lwdata.srl:60'),  # spec 15.2.5.3 config-0-lwdata.srl:60
        ('put', 'u32', (1,), '15.2.5.3 config-0-lwdata.srl:61'),  # spec 15.2.5.3 config-0-lwdata.srl:61
        ('put', 'u32', (32764,), '15.2.5.3 config-0-lwdata.srl:41'),  # spec 15.2.5.3 config-0-lwdata.srl:41
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:42'),  # spec 15.2.5.3 config-0-lwdata.srl:42
        ('put', 'f64', (1.0,), '15.2.5.3 config-0-lwdata.srl:43'),  # spec 15.2.5.3 config-0-lwdata.srl:43
        ('put', 'f64', (0.0,), '15.2.5.3 config-0-lwdata.srl:44'),  # spec 15.2.5.3 config-0-lwdata.srl:44
        ('put', 'i32', (-4,), '15.2.5.3 config-0-lwdata.srl:45'),  # spec 15.2.5.3 config-0-lwdata.srl:45
        ('put', 'f64', (('$', 'planes.front.hu'), ('=', '-$planes.front.hu')), '15.2.5.3 config-0-lwdata.srl:46'),  # spec 15.2.5.3 config-0-lwdata.srl:46
        ('put', 'f64', (('$', 'planes.front.hv'), ('=', '-$planes.front.hv')), '15.2.5.3 config-0-lwdata.srl:47'),  # spec 15.2.5.3 config-0-lwdata.srl:47
        ('put', 'cstr', ('moDefaultRefPlnData_c',), '15.2.5.3 config-0-lwdata.srl:48'),  # spec 15.2.5.3 config-0-lwdata.srl:48
        ('class', 'moLWPlaneNodeData_c', 1, None, '15.2.5.3 config-0-lwdata.srl:63'),  # spec 15.2.5.3 config-0-lwdata.srl:63
        ('put', 'cstr', ('moRefPlane_c',), '15.2.5.3 config-0-lwdata.srl:64'),  # spec 15.2.5.3 config-0-lwdata.srl:64
        ('put', 'cstr', ('Top Plane',), '15.2.5.3 config-0-lwdata.srl:65'),  # spec 15.2.5.3 config-0-lwdata.srl:65
        ('put', 'u32', (3,), '15.2.5.3 config-0-lwdata.srl:66'),  # spec 15.2.5.3 config-0-lwdata.srl:66
        ('put', 'u32', (0, 1), '15.2.5.3 config-0-lwdata.srl:67'),  # spec 15.2.5.3 config-0-lwdata.srl:67
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:68'),  # spec 15.2.5.3 config-0-lwdata.srl:68
        ('put', 'f64', (0.0, 1.0, 0.0), '15.2.5.3 config-0-lwdata.srl:69'),  # spec 15.2.5.3 config-0-lwdata.srl:69
        ('put', 'f64', (('$', 'planes.top.centre.0'), ('$', 'planes.top.centre.1'), ('$', 'planes.top.centre.2')), '15.2.5.3 config-0-lwdata.srl:35'),  # spec 15.2.5.3 config-0-lwdata.srl:35
        ('put', 'f64', (('$', 'planes.top.max.0'), ('$', 'planes.top.max.1'), ('$', 'planes.top.max.2')), '15.2.5.3 config-0-lwdata.srl:36'),  # spec 15.2.5.3 config-0-lwdata.srl:36
        ('put', 'f64', (('$', 'planes.top.min.0'), ('$', 'planes.top.min.1'), ('$', 'planes.top.min.2')), '15.2.5.3 config-0-lwdata.srl:37'),  # spec 15.2.5.3 config-0-lwdata.srl:37
        ('put', 'f64', (('$', 'planes.top.radius'),), '15.2.5.3 config-0-lwdata.srl:38'),  # spec 15.2.5.3 config-0-lwdata.srl:38
        ('put', 'f64', (1.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:71'),  # spec 15.2.5.3 config-0-lwdata.srl:71
        ('put', 'f64', (0.0, 0.0, 1.0), '15.2.5.3 config-0-lwdata.srl:72'),  # spec 15.2.5.3 config-0-lwdata.srl:72
        ('put', 'f64', (0.0, -1.0, 0.0), '15.2.5.3 config-0-lwdata.srl:73'),  # spec 15.2.5.3 config-0-lwdata.srl:73
        ('put', 'u32', (0,), '15.2.5.3 config-0-lwdata.srl:74'),  # spec 15.2.5.3 config-0-lwdata.srl:74
        ('put', 'u32', (32764,), '15.2.5.3 config-0-lwdata.srl:41'),  # spec 15.2.5.3 config-0-lwdata.srl:41
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:42'),  # spec 15.2.5.3 config-0-lwdata.srl:42
        ('put', 'f64', (1.0,), '15.2.5.3 config-0-lwdata.srl:43'),  # spec 15.2.5.3 config-0-lwdata.srl:43
        ('put', 'f64', (0.0,), '15.2.5.3 config-0-lwdata.srl:44'),  # spec 15.2.5.3 config-0-lwdata.srl:44
        ('put', 'i32', (-4,), '15.2.5.3 config-0-lwdata.srl:45'),  # spec 15.2.5.3 config-0-lwdata.srl:45
        ('put', 'f64', (('$', 'planes.top.hu'), ('=', '-$planes.top.hu')), '15.2.5.3 config-0-lwdata.srl:46'),  # spec 15.2.5.3 config-0-lwdata.srl:46
        ('put', 'f64', (('$', 'planes.top.hv'), ('=', '-$planes.top.hv')), '15.2.5.3 config-0-lwdata.srl:47'),  # spec 15.2.5.3 config-0-lwdata.srl:47
        ('put', 'cstr', ('moDefaultRefPlnData_c',), '15.2.5.3 config-0-lwdata.srl:48'),  # spec 15.2.5.3 config-0-lwdata.srl:48
        ('class', 'moLWPlaneNodeData_c', 1, None, '15.2.5.3 config-0-lwdata.srl:76'),  # spec 15.2.5.3 config-0-lwdata.srl:76
        ('put', 'cstr', ('moRefPlane_c',), '15.2.5.3 config-0-lwdata.srl:77'),  # spec 15.2.5.3 config-0-lwdata.srl:77
        ('put', 'cstr', ('Right Plane',), '15.2.5.3 config-0-lwdata.srl:78'),  # spec 15.2.5.3 config-0-lwdata.srl:78
        ('put', 'u32', (4,), '15.2.5.3 config-0-lwdata.srl:79'),  # spec 15.2.5.3 config-0-lwdata.srl:79
        ('put', 'u32', (0, 1), '15.2.5.3 config-0-lwdata.srl:80'),  # spec 15.2.5.3 config-0-lwdata.srl:80
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:81'),  # spec 15.2.5.3 config-0-lwdata.srl:81
        ('put', 'f64', (1.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:82'),  # spec 15.2.5.3 config-0-lwdata.srl:82
        ('put', 'f64', (('$', 'planes.right.centre.0'), ('$', 'planes.right.centre.1'), ('$', 'planes.right.centre.2')), '15.2.5.3 config-0-lwdata.srl:35'),  # spec 15.2.5.3 config-0-lwdata.srl:35
        ('put', 'f64', (('$', 'planes.right.max.0'), ('$', 'planes.right.max.1'), ('$', 'planes.right.max.2')), '15.2.5.3 config-0-lwdata.srl:36'),  # spec 15.2.5.3 config-0-lwdata.srl:36
        ('put', 'f64', (('$', 'planes.right.min.0'), ('$', 'planes.right.min.1'), ('$', 'planes.right.min.2')), '15.2.5.3 config-0-lwdata.srl:37'),  # spec 15.2.5.3 config-0-lwdata.srl:37
        ('put', 'f64', (('$', 'planes.right.radius'),), '15.2.5.3 config-0-lwdata.srl:38'),  # spec 15.2.5.3 config-0-lwdata.srl:38
        ('put', 'f64', (-0.0, 0.0, 1.0), '15.2.5.3 config-0-lwdata.srl:84'),  # spec 15.2.5.3 config-0-lwdata.srl:84
        ('put', 'f64', (-0.0, 1.0, 0.0), '15.2.5.3 config-0-lwdata.srl:85'),  # spec 15.2.5.3 config-0-lwdata.srl:85
        ('put', 'f64', (-1.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:86'),  # spec 15.2.5.3 config-0-lwdata.srl:86
        ('put', 'u32', (0,), '15.2.5.3 config-0-lwdata.srl:87'),  # spec 15.2.5.3 config-0-lwdata.srl:87
        ('put', 'u32', (32764,), '15.2.5.3 config-0-lwdata.srl:41'),  # spec 15.2.5.3 config-0-lwdata.srl:41
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.5.3 config-0-lwdata.srl:42'),  # spec 15.2.5.3 config-0-lwdata.srl:42
        ('put', 'f64', (1.0,), '15.2.5.3 config-0-lwdata.srl:43'),  # spec 15.2.5.3 config-0-lwdata.srl:43
        ('put', 'f64', (0.0,), '15.2.5.3 config-0-lwdata.srl:44'),  # spec 15.2.5.3 config-0-lwdata.srl:44
        ('put', 'i32', (-4,), '15.2.5.3 config-0-lwdata.srl:45'),  # spec 15.2.5.3 config-0-lwdata.srl:45
        ('put', 'f64', (('$', 'planes.right.hu'), ('=', '-$planes.right.hu')), '15.2.5.3 config-0-lwdata.srl:46'),  # spec 15.2.5.3 config-0-lwdata.srl:46
        ('put', 'f64', (('$', 'planes.right.hv'), ('=', '-$planes.right.hv')), '15.2.5.3 config-0-lwdata.srl:47'),  # spec 15.2.5.3 config-0-lwdata.srl:47
        ('put', 'cstr', ('moDefaultRefPlnData_c',), '15.2.5.3 config-0-lwdata.srl:48'),  # spec 15.2.5.3 config-0-lwdata.srl:48
        ('rep', 6, 0, '15.2.5.4 config-0-lwdata.srl:91'),  # spec 15.2.5.4 config-0-lwdata.srl:91
        ('put', 'u32', (('=', 'len($features)>0'),), '15.2.5.4 config-0-lwdata.srl:92'),  # spec 15.2.5.4 config-0-lwdata.srl:92
        ('put', 'u32', (('$', 'lw.flag'),), '15.2.5.4 config-0-lwdata.srl:93'),  # spec 15.2.5.4 config-0-lwdata.srl:93
        ('rep', 8, 0, '15.2.5.4 config-0-lwdata.srl:94'),  # spec 15.2.5.4 config-0-lwdata.srl:94
    ),  # spec 15.2 config-0-lwdata.srl
    'Contents/Config-0-ModelHeader': (  # spec 15.2 config-0-modelheader.srl
        ('archive', 'start', 1, '15.2.2 model-header.srl:4'),  # spec 15.2.2 model-header.srl:4
        ('class', 'moHeader_c', 1, None, '15.2.2.1 model-header.srl:6'),  # spec 15.2.2.1 model-header.srl:6
        ('put', 'u32', (1,), '15.2.2.1 model-header.srl:7'),  # spec 15.2.2.1 model-header.srl:7
        ('class', 'su_CStringArray', 0, None, '15.2.2.1 model-header.srl:8'),  # spec 15.2.2.1 model-header.srl:8
        ('put', 'u16', (1,), '15.2.2.1 model-header.srl:9'),  # spec 15.2.2.1 model-header.srl:9
        ('put', 'cstr', (('$', 'doc.author'),), '15.2.2.1 model-header.srl:10'),  # spec 15.2.2.1 model-header.srl:10
        ('class', 'su_CStringArray', 0, None, '15.2.2.1 model-header.srl:11'),  # spec 15.2.2.1 model-header.srl:11
        ('put', 'u16', (1,), '15.2.2.1 model-header.srl:12'),  # spec 15.2.2.1 model-header.srl:12
        ('put', 'cstr', ('',), '15.2.2.1 model-header.srl:13'),  # spec 15.2.2.1 model-header.srl:13
        ('class', 'suObList', 1, None, '15.2.2.2 model-header.srl:32'),  # spec 15.2.2.2 model-header.srl:32
        ('put', 'u16', (('=', '24+len($features)'),), '15.2.2.2 model-header.srl:33'),  # spec 15.2.2.2 model-header.srl:33
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:35'),  # spec 15.2.2.2 model-header.srl:35
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:36'),  # spec 15.2.2.2 model-header.srl:36
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:38'),  # spec 15.2.2.2 model-header.srl:38
        ('put', 'cstr', ('Part1^Assem1',), '15.2.2.2 model-header.srl:39'),  # spec 15.2.2.2 model-header.srl:39
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:40'),  # spec 15.2.2.2 model-header.srl:40
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:41'),  # spec 15.2.2.2 model-header.srl:41
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (1,), '15.2.2.2 model-header.srl:43'),  # spec 15.2.2.2 model-header.srl:43
        ('put', 'cstr', ('Annotations',), '15.2.2.2 model-header.srl:44'),  # spec 15.2.2.2 model-header.srl:44
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:45'),  # spec 15.2.2.2 model-header.srl:45
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:46'),  # spec 15.2.2.2 model-header.srl:46
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (2,), '15.2.2.2 model-header.srl:49'),  # spec 15.2.2.2 model-header.srl:49
        ('put', 'cstr', ('Front Plane',), '15.2.2.2 model-header.srl:50'),  # spec 15.2.2.2 model-header.srl:50
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:51'),  # spec 15.2.2.2 model-header.srl:51
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:52'),  # spec 15.2.2.2 model-header.srl:52
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (3,), '15.2.2.2 model-header.srl:55'),  # spec 15.2.2.2 model-header.srl:55
        ('put', 'cstr', ('Top Plane',), '15.2.2.2 model-header.srl:56'),  # spec 15.2.2.2 model-header.srl:56
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:57'),  # spec 15.2.2.2 model-header.srl:57
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:58'),  # spec 15.2.2.2 model-header.srl:58
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (4,), '15.2.2.2 model-header.srl:61'),  # spec 15.2.2.2 model-header.srl:61
        ('put', 'cstr', ('Right Plane',), '15.2.2.2 model-header.srl:62'),  # spec 15.2.2.2 model-header.srl:62
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:63'),  # spec 15.2.2.2 model-header.srl:63
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:64'),  # spec 15.2.2.2 model-header.srl:64
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (5,), '15.2.2.2 model-header.srl:67'),  # spec 15.2.2.2 model-header.srl:67
        ('put', 'cstr', ('Origin',), '15.2.2.2 model-header.srl:68'),  # spec 15.2.2.2 model-header.srl:68
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:69'),  # spec 15.2.2.2 model-header.srl:69
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:70'),  # spec 15.2.2.2 model-header.srl:70
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (6,), '15.2.2.2 model-header.srl:72'),  # spec 15.2.2.2 model-header.srl:72
        ('put', 'cstr', ('Lights and Cameras',), '15.2.2.2 model-header.srl:73'),  # spec 15.2.2.2 model-header.srl:73
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:74'),  # spec 15.2.2.2 model-header.srl:74
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:75'),  # spec 15.2.2.2 model-header.srl:75
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (7,), '15.2.2.2 model-header.srl:77'),  # spec 15.2.2.2 model-header.srl:77
        ('put', 'cstr', ('Design Binder',), '15.2.2.2 model-header.srl:78'),  # spec 15.2.2.2 model-header.srl:78
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:79'),  # spec 15.2.2.2 model-header.srl:79
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:80'),  # spec 15.2.2.2 model-header.srl:80
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (8,), '15.2.2.2 model-header.srl:82'),  # spec 15.2.2.2 model-header.srl:82
        ('put', 'cstr', ('Comments',), '15.2.2.2 model-header.srl:83'),  # spec 15.2.2.2 model-header.srl:83
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:84'),  # spec 15.2.2.2 model-header.srl:84
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:85'),  # spec 15.2.2.2 model-header.srl:85
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (9,), '15.2.2.2 model-header.srl:87'),  # spec 15.2.2.2 model-header.srl:87
        ('put', 'cstr', ('Solid Bodies',), '15.2.2.2 model-header.srl:88'),  # spec 15.2.2.2 model-header.srl:88
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:89'),  # spec 15.2.2.2 model-header.srl:89
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:90'),  # spec 15.2.2.2 model-header.srl:90
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (10,), '15.2.2.2 model-header.srl:92'),  # spec 15.2.2.2 model-header.srl:92
        ('put', 'cstr', ('Surface Bodies',), '15.2.2.2 model-header.srl:93'),  # spec 15.2.2.2 model-header.srl:93
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:94'),  # spec 15.2.2.2 model-header.srl:94
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:95'),  # spec 15.2.2.2 model-header.srl:95
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (11,), '15.2.2.2 model-header.srl:98'),  # spec 15.2.2.2 model-header.srl:98
        ('put', 'cstr', ('Material <not specified>',), '15.2.2.2 model-header.srl:99'),  # spec 15.2.2.2 model-header.srl:99
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:100'),  # spec 15.2.2.2 model-header.srl:100
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:101'),  # spec 15.2.2.2 model-header.srl:101
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (12,), '15.2.2.2 model-header.srl:103'),  # spec 15.2.2.2 model-header.srl:103
        ('put', 'cstr', ('Ambient',), '15.2.2.2 model-header.srl:104'),  # spec 15.2.2.2 model-header.srl:104
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:105'),  # spec 15.2.2.2 model-header.srl:105
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:106'),  # spec 15.2.2.2 model-header.srl:106
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (13,), '15.2.2.2 model-header.srl:108'),  # spec 15.2.2.2 model-header.srl:108
        ('put', 'cstr', ('Directional1',), '15.2.2.2 model-header.srl:109'),  # spec 15.2.2.2 model-header.srl:109
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:110'),  # spec 15.2.2.2 model-header.srl:110
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:111'),  # spec 15.2.2.2 model-header.srl:111
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (14,), '15.2.2.2 model-header.srl:113'),  # spec 15.2.2.2 model-header.srl:113
        ('put', 'cstr', ('Directional2',), '15.2.2.2 model-header.srl:114'),  # spec 15.2.2.2 model-header.srl:114
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:115'),  # spec 15.2.2.2 model-header.srl:115
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:116'),  # spec 15.2.2.2 model-header.srl:116
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (15,), '15.2.2.2 model-header.srl:118'),  # spec 15.2.2.2 model-header.srl:118
        ('put', 'cstr', ('Directional3',), '15.2.2.2 model-header.srl:119'),  # spec 15.2.2.2 model-header.srl:119
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:120'),  # spec 15.2.2.2 model-header.srl:120
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:121'),  # spec 15.2.2.2 model-header.srl:121
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (16,), '15.2.2.2 model-header.srl:123'),  # spec 15.2.2.2 model-header.srl:123
        ('put', 'cstr', ('Equations',), '15.2.2.2 model-header.srl:124'),  # spec 15.2.2.2 model-header.srl:124
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:126'),  # spec 15.2.2.2 model-header.srl:126
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:127'),  # spec 15.2.2.2 model-header.srl:127
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (17,), '15.2.2.2 model-header.srl:129'),  # spec 15.2.2.2 model-header.srl:129
        ('put', 'cstr', ('Notes',), '15.2.2.2 model-header.srl:130'),  # spec 15.2.2.2 model-header.srl:130
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:131'),  # spec 15.2.2.2 model-header.srl:131
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:132'),  # spec 15.2.2.2 model-header.srl:132
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (18,), '15.2.2.2 model-header.srl:134'),  # spec 15.2.2.2 model-header.srl:134
        ('put', 'cstr', ('Notes1___EndTag___',), '15.2.2.2 model-header.srl:135'),  # spec 15.2.2.2 model-header.srl:135
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:136'),  # spec 15.2.2.2 model-header.srl:136
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:137'),  # spec 15.2.2.2 model-header.srl:137
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (21,), '15.2.2.2 model-header.srl:139'),  # spec 15.2.2.2 model-header.srl:139
        ('put', 'cstr', ('Markups',), '15.2.2.2 model-header.srl:140'),  # spec 15.2.2.2 model-header.srl:140
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:141'),  # spec 15.2.2.2 model-header.srl:141
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:142'),  # spec 15.2.2.2 model-header.srl:142
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (22,), '15.2.2.2 model-header.srl:144'),  # spec 15.2.2.2 model-header.srl:144
        ('put', 'cstr', ('Sensors',), '15.2.2.2 model-header.srl:145'),  # spec 15.2.2.2 model-header.srl:145
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:146'),  # spec 15.2.2.2 model-header.srl:146
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:147'),  # spec 15.2.2.2 model-header.srl:147
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (23,), '15.2.2.2 model-header.srl:149'),  # spec 15.2.2.2 model-header.srl:149
        ('put', 'cstr', ('Favorites',), '15.2.2.2 model-header.srl:150'),  # spec 15.2.2.2 model-header.srl:150
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:151'),  # spec 15.2.2.2 model-header.srl:151
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:152'),  # spec 15.2.2.2 model-header.srl:152
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (24,), '15.2.2.2 model-header.srl:154'),  # spec 15.2.2.2 model-header.srl:154
        ('put', 'cstr', ('Folder ',), '15.2.2.2 model-header.srl:155'),  # spec 15.2.2.2 model-header.srl:155
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:156'),  # spec 15.2.2.2 model-header.srl:156
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:157'),  # spec 15.2.2.2 model-header.srl:157
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (25,), '15.2.2.2 model-header.srl:159'),  # spec 15.2.2.2 model-header.srl:159
        ('put', 'cstr', ('Selection Sets',), '15.2.2.2 model-header.srl:160'),  # spec 15.2.2.2 model-header.srl:160
        ('for', 'f', ('$', 'features'), False, (  # spec 15.2.2.2 model-header.srl:162
            ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:163'),  # spec 15.2.2.2 model-header.srl:163
            ('if', ('$', 'f.sketch'), (  # spec 15.2.2.2 model-header.srl:164
                ('put', 'u16', (2,), '15.2.2.2 model-header.srl:165'),  # spec 15.2.2.2 model-header.srl:165
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
                ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
                ('put', 'u32', (('$', 'f.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
                ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
                ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
                ('put', 'u32', (('$', 'f.modified'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
                ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
            ), (  # spec 15.2.2.2 model-header.srl:164
                ('put', 'u16', (1,), '15.2.2.2 model-header.srl:169'),  # spec 15.2.2.2 model-header.srl:169
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
                ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
                ('put', 'u32', (('$', 'f.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
                ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
            ), '15.2.2.2 model-header.srl:164'),  # spec 15.2.2.2 model-header.srl:164
            ('put', 'u32', (('$', 'f.id'),), '15.2.2.2 model-header.srl:172'),  # spec 15.2.2.2 model-header.srl:172
            ('put', 'cstr', (('$', 'f.name'),), '15.2.2.2 model-header.srl:173'),  # spec 15.2.2.2 model-header.srl:173
        ), '15.2.2.2 model-header.srl:162'),  # spec 15.2.2.2 model-header.srl:162
        ('put', 'u32', (('$', 'tpl.unix2'),), '15.2.2.2 model-header.srl:175'),  # spec 15.2.2.2 model-header.srl:175
        ('put', 'u32', (('$', 'hdr.next_id'),), '15.2.2.2 model-header.srl:176'),  # spec 15.2.2.2 model-header.srl:176
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:177'),  # spec 15.2.2.2 model-header.srl:177
        ('put', 'u32', (('$', 'doc.stamp'),), '15.2.2.2 model-header.srl:178'),  # spec 15.2.2.2 model-header.srl:178
        ('class', 'moExtObject_c', 1, None, '15.2.2.5 model-header.srl:181'),  # spec 15.2.2.5 model-header.srl:181
        ('class', 'moCStringHandle_c', 1, None, '15.2.2.5 model-header.srl:182'),  # spec 15.2.2.5 model-header.srl:182
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:183'),  # spec 15.2.2.5 model-header.srl:183
        ('class', 'moCStringHandle_c', 1, None, '15.2.2.5 model-header.srl:184'),  # spec 15.2.2.5 model-header.srl:184
        ('put', 'cstr', (('$', 'doc.name'),), '15.2.2.5 model-header.srl:185'),  # spec 15.2.2.5 model-header.srl:185
        ('hex', '020000', '15.2.2.5 model-header.srl:186'),  # spec 15.2.2.5 model-header.srl:186
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.5 model-header.srl:187'),  # spec 15.2.2.5 model-header.srl:187
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:188'),  # spec 15.2.2.5 model-header.srl:188
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:189'),  # spec 15.2.2.5 model-header.srl:189
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:190'),  # spec 15.2.2.5 model-header.srl:190
        ('put', 'u16', (0,), '15.2.2.5 model-header.srl:191'),  # spec 15.2.2.5 model-header.srl:191
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.2.5 model-header.srl:192
            ('put', 'u32', (('$', 'doc.unix'),), '15.2.2.5 model-header.srl:193'),  # spec 15.2.2.5 model-header.srl:193
        ), (  # spec 15.2.2.5 model-header.srl:192
            ('put', 'u32', (('$', 'tpl.unix2'),), '15.2.2.5 model-header.srl:195'),  # spec 15.2.2.5 model-header.srl:195
        ), '15.2.2.5 model-header.srl:192'),  # spec 15.2.2.5 model-header.srl:192
        ('put', 'u32', (1, 0), '15.2.2.5 model-header.srl:197'),  # spec 15.2.2.5 model-header.srl:197
        ('put', 'i32', (-1,), '15.2.2.5 model-header.srl:198'),  # spec 15.2.2.5 model-header.srl:198
        ('put', 'cstr', ('Default',), '15.2.2.5 model-header.srl:199'),  # spec 15.2.2.5 model-header.srl:199
        ('rep', 16, 0, '15.2.2.5 model-header.srl:200'),  # spec 15.2.2.5 model-header.srl:200
        ('put', 'u32', (('$', 'doc.stamp2'),), '15.2.2.5 model-header.srl:201'),  # spec 15.2.2.5 model-header.srl:201
        ('put', 'u32', (0, 0), '15.2.2.5 model-header.srl:202'),  # spec 15.2.2.5 model-header.srl:202
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.5 model-header.srl:203'),  # spec 15.2.2.5 model-header.srl:203
        ('rep', 18, 0, '15.2.2.5 model-header.srl:204'),  # spec 15.2.2.5 model-header.srl:204
        ('put', 'u32', (2,), '15.2.2.5 model-header.srl:205'),  # spec 15.2.2.5 model-header.srl:205
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.2.5 model-header.srl:206
            ('put', 'u32', (('$', 'doc.unix'),), '15.2.2.5 model-header.srl:207'),  # spec 15.2.2.5 model-header.srl:207
        ), (  # spec 15.2.2.5 model-header.srl:206
            ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.5 model-header.srl:209'),  # spec 15.2.2.5 model-header.srl:209
        ), '15.2.2.5 model-header.srl:206'),  # spec 15.2.2.5 model-header.srl:206
        ('class', 'suObList', 1, None, '15.2.2.5 model-header.srl:211'),  # spec 15.2.2.5 model-header.srl:211
        ('put', 'u16', (0,), '15.2.2.5 model-header.srl:212'),  # spec 15.2.2.5 model-header.srl:212
        ('put', 'u32', (0, 0), '15.2.2.5 model-header.srl:213'),  # spec 15.2.2.5 model-header.srl:213
        ('if', ('$', 'model.solid'), (  # spec 15.2.2.6 model-header.srl:217
            ('put', 'u32', (1,), '15.2.2.6 model-header.srl:218'),  # spec 15.2.2.6 model-header.srl:218
            ('put', 'f64', (('$', 'hdr.centre.0'), ('$', 'hdr.centre.1'), ('$', 'hdr.centre.2')), '15.2.2.6 model-header.srl:219'),  # spec 15.2.2.6 model-header.srl:219
            ('put', 'f64', (('$', 'model.max.0'), ('$', 'model.max.1'), ('$', 'model.max.2')), '15.2.2.6 model-header.srl:220'),  # spec 15.2.2.6 model-header.srl:220
            ('put', 'f64', (('$', 'model.min.0'), ('$', 'model.min.1'), ('$', 'model.min.2')), '15.2.2.6 model-header.srl:221'),  # spec 15.2.2.6 model-header.srl:221
            ('put', 'f64', (('$', 'model.sphere.3'),), '15.2.2.6 model-header.srl:222'),  # spec 15.2.2.6 model-header.srl:222
        ), (  # spec 15.2.2.6 model-header.srl:217
            ('put', 'u32', (0,), '15.2.2.6 model-header.srl:224'),  # spec 15.2.2.6 model-header.srl:224
        ), '15.2.2.6 model-header.srl:217'),  # spec 15.2.2.6 model-header.srl:217
        ('put', 'i32', (-1, -1, -1), '15.2.2.6 model-header.srl:226'),  # spec 15.2.2.6 model-header.srl:226
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:227'),  # spec 15.2.2.6 model-header.srl:227
        ('rep', 40, 0, '15.2.2.6 model-header.srl:228'),  # spec 15.2.2.6 model-header.srl:228
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:229'),  # spec 15.2.2.6 model-header.srl:229
        ('rep', 16, 0, '15.2.2.6 model-header.srl:230'),  # spec 15.2.2.6 model-header.srl:230
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:231'),  # spec 15.2.2.6 model-header.srl:231
    ),  # spec 15.2 config-0-modelheader.srl
    'Contents/Config-0-ResolvedFeatures': (  # spec 15.5 config-0-resolvedfeatures.srl
        ('archive', 'continue', None, '15.5.1 config-0-resolvedfeatures.srl:6'),  # spec 15.5.1 config-0-resolvedfeatures.srl:6
        ('archive', 'set', 'header', '15.5.1 config-0-resolvedfeatures.srl:7'),  # spec 15.5.1 config-0-resolvedfeatures.srl:7
        ('put', 'u32', (('$', '_archive.header'),), '15.5.1 config-0-resolvedfeatures.srl:8'),  # spec 15.5.1 config-0-resolvedfeatures.srl:8
        ('put', 'u16', (('=', '17+len($features)'),), '15.5.1 config-0-resolvedfeatures.srl:9'),  # spec 15.5.1 config-0-resolvedfeatures.srl:9
        ('class', 'moCommentsFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:5'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:5
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Comments',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 8, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:7'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:7
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+0'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.comments.time//4294967296'), ('=', '$fixed.comments.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.comments.time//4294967296'), ('=', '$fixed.comments.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 0, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:9'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:9
        ('class', 'moFavoriteFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:10'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:10
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Favorites',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 23, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:12'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:12
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+1'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.favorites.time//4294967296'), ('=', '$fixed.favorites.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.favorites.time//4294967296'), ('=', '$fixed.favorites.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1, 0, 0, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:14'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:14
        ('class', 'moHistoryFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:15'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:15
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Folder ',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 24, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:17'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:17
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+2'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.history.time//4294967296'), ('=', '$fixed.history.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.history.time//4294967296'), ('=', '$fixed.history.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:19'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:19
        ('put', 'u16', (('=', 'len($features)'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:20'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:20
        ('for', 'f', ('$', 'features'), False, (  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:21
            ('class', 'moHistoryFeatItemData_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:23'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:23
            ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:24'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:24
            ('put', 'u32', (1, 1073741824), '15.5.3 config-0-resolvedfeatures-fixed.srl:25'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:25
            ('put', 'i32', (-1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:26'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:26
            ('put', 'u32', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:27'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:27
            ('put', 'cstr', ('',), '15.5.3 config-0-resolvedfeatures-fixed.srl:28'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:28
            ('class', 'moCompFeature_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:29'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:29
            ('class', 'moUnitComponent_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:30'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:30
            ('put', 'u16', (2,), '15.5.3 config-0-resolvedfeatures-fixed.srl:31'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:31
            ('rep', 41, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:32'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:32
            ('put', 'i32', (-1, -1, -1, -1), '15.5.3 config-0-resolvedfeatures-fixed.srl:33'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:33
            ('rep', 20, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:34'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:34
            ('put', 'u32', (17000, ('$', 'f.id'), ('$', 'f.created')), '15.5.3 config-0-resolvedfeatures-fixed.srl:35'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:35
        ), '15.5.3 config-0-resolvedfeatures-fixed.srl:21'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:21
        ('class', 'moSelectionSetFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:37'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:37
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Selection Sets',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 25, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:39'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:39
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+3'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.selsets.time//4294967296'), ('=', '$fixed.selsets.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.selsets.time//4294967296'), ('=', '$fixed.selsets.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:41'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:41
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:42'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:42
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:43'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:43
        ('class', 'moSensorFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:44'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:44
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Sensors',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 22, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:46'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:46
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.sensors.time//4294967296'), ('=', '$fixed.sensors.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:48'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:48
        ('class', 'moDocsFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:49'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:49
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Design Binder',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 7, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:51'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:51
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+4'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.binder.time//4294967296'), ('=', '$fixed.binder.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.binder.time//4294967296'), ('=', '$fixed.binder.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:53'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:53
        ('class', 'moDetailCabinet_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:54'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:54
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Annotations',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 1, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (2,), '15.5.3 config-0-resolvedfeatures-fixed.srl:56'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:56
        ('class', 'moNotesAreaFtrFolder_c', 1, 'notes', '15.5.3 config-0-resolvedfeatures-fixed.srl:57'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:57
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Notes',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 17, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:59'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:59
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.notes.time//4294967296'), ('=', '$fixed.notes.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:61'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:61
        ('class', 'moNotesAreaFtrFolder_c', 1, 'notes_end', '15.5.3 config-0-resolvedfeatures-fixed.srl:62'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:62
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Notes1___EndTag___',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 18, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:64'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:64
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.notes_end.time//4294967296'), ('=', '$fixed.notes_end.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:66'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:66
        ('objref', 'notes', '15.5.3 config-0-resolvedfeatures-fixed.srl:67'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:67
        ('put', 'u32', (0, 0, 1, 1, 1, 0, 1, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:68'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:68
        ('objref', 'notes_end', '15.5.3 config-0-resolvedfeatures-fixed.srl:69'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:69
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+5'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.annotations.time//4294967296'), ('=', '$fixed.annotations.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.annotations.time//4294967296'), ('=', '$fixed.annotations.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:71'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:71
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:72'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:72
        ('put', 'f64', (1.0, 1.0), '15.5.3 config-0-resolvedfeatures-fixed.srl:73'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:73
        ('rep', 10, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:74'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:74
        ('class', 'moSurfaceBodyFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:75'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:75
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Surface Bodies',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 10, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:77'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:77
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+6'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.surface.time//4294967296'), ('=', '$fixed.surface.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.surface.time//4294967296'), ('=', '$fixed.surface.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:79'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:79
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:80'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:80
        ('class', 'moSolidBodyFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:81'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:81
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Solid Bodies',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 9, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:83'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:83
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+7'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.solid.time//4294967296'), ('=', '$fixed.solid.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.solid.time//4294967296'), ('=', '$fixed.solid.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:85'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:85
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:86'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:86
        ('objref', 'env_folder', '15.5.3 config-0-resolvedfeatures-fixed.srl:87'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:87
        ('class', 'moInkMarkupFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:88'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:88
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Markups',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 21, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:90'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:90
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.markups.time//4294967296'), ('=', '$fixed.markups.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:92'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:92
        ('class', 'moEqnFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:93'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:93
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Equations',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 16, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:95'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:95
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '0x1da7f0beab12577//4294967296'), ('=', '0x1da7f0beab12577%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:97'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:97
        ('class', 'moMaterialFolder_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:98'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:98
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Material <not specified>',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 1073741824, 11, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:100'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:100
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+9'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.material.time//4294967296'), ('=', '$fixed.material.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.material.time//4294967296'), ('=', '$fixed.material.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:102'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:102
        ('put', 'cstr', ('',), '15.5.3 config-0-resolvedfeatures-fixed.srl:103'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:103
        ('put', 'u32', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:104'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:104
        ('class', 'moRefPlane_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:105'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:105
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Front Plane',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 3221225472, 2, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:107'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:107
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.front.time//4294967296'), ('=', '$fixed.front.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:110'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:110
        ('rep', 38, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:111'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:111
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:112'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:112
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:113'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:113
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:114'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:114
        ('rep', 54, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:115'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:115
        ('put', 'f64', (('=', '$model.centre.0-$planes.front.hu'), ('=', '$model.centre.1+$planes.front.hv'), 0.0), '15.5.3 config-0-resolvedfeatures-fixed.srl:116'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:116
        ('put', 'u32', (5,), '15.5.3 config-0-resolvedfeatures-fixed.srl:117'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:117
        ('rep', 10, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:118'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:118
        ('class', 'moDefaultRefPlnData_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:119'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:119
        ('rep', 40, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:120'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:120
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:121'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:121
        ('rep', 25, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:122'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:122
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:123'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:123
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:124'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:124
        ('put', 'f64', (('$', 'planes.front.hu'), ('=', '-$planes.front.hu'), ('$', 'planes.front.hv'), ('=', '-$planes.front.hv')), '15.5.3 config-0-resolvedfeatures-fixed.srl:125'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:125
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:126'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:126
        ('put', 'i32', (-4, -4), '15.5.3 config-0-resolvedfeatures-fixed.srl:127'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:127
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:128'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:128
        ('put', 'f64', (('$', 'model.centre.0'), ('$', 'model.centre.1'), 0.0), '15.5.3 config-0-resolvedfeatures-fixed.srl:129'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:129
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:130'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:130
        ('rep', 12, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:131'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:131
        ('class', 'moRefPlane_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:132'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:132
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Top Plane',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 3221225472, 3, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:134'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:134
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.top.time//4294967296'), ('=', '$fixed.top.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:137'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:137
        ('rep', 38, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:138'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:138
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:139'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:139
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:140'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:140
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:141'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:141
        ('rep', 54, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:142'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:142
        ('put', 'f64', (('=', '$model.centre.0-$planes.top.hu'), 0.0, ('=', '$model.centre.2-$planes.top.hv')), '15.5.3 config-0-resolvedfeatures-fixed.srl:143'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:143
        ('put', 'u32', (5,), '15.5.3 config-0-resolvedfeatures-fixed.srl:144'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:144
        ('rep', 10, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:145'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:145
        ('class', 'moDefaultRefPlnData_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:146'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:146
        ('rep', 32, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:147'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:147
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:148'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:148
        ('put', 'u32', (0, 0, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:149'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:149
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:150'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:150
        ('put', 'f32', (1.875,), '15.5.3 config-0-resolvedfeatures-fixed.srl:151'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:151
        ('rep', 32, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:152'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:152
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:153'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:153
        ('put', 'u32', (0, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:154'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:154
        ('put', 'f64', (-1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:155'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:155
        ('rep', 32, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:156'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:156
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:157'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:157
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:158'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:158
        ('put', 'f64', (('$', 'planes.top.hu'), ('=', '-$planes.top.hu'), ('$', 'planes.top.hv'), ('=', '-$planes.top.hv')), '15.5.3 config-0-resolvedfeatures-fixed.srl:159'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:159
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:160'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:160
        ('put', 'i32', (-4, -4), '15.5.3 config-0-resolvedfeatures-fixed.srl:161'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:161
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:162'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:162
        ('put', 'f64', (('$', 'model.centre.0'), 0.0, ('$', 'model.centre.2')), '15.5.3 config-0-resolvedfeatures-fixed.srl:163'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:163
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:164'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:164
        ('rep', 12, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:165'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:165
        ('class', 'moRefPlane_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:166'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:166
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Right Plane',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 3221225472, 4, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:168'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:168
        ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
        ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
        ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
        ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
        ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
        ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
        ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
        ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
        ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
        ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
        ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
        ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
        ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
        ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
        ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
        ('put', 'u32', (('=', '$fixed.right.time//4294967296'), ('=', '$fixed.right.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
        ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
        ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:171'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:171
        ('rep', 38, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:172'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:172
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:173'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:173
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:174'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:174
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:175'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:175
        ('rep', 54, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:176'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:176
        ('put', 'f64', (0.0, ('=', '$model.centre.1+$planes.right.hv'), ('=', '$model.centre.2+$planes.right.hu')), '15.5.3 config-0-resolvedfeatures-fixed.srl:177'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:177
        ('put', 'u32', (5,), '15.5.3 config-0-resolvedfeatures-fixed.srl:178'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:178
        ('rep', 10, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:179'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:179
        ('class', 'moDefaultRefPlnData_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:180'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:180
        ('rep', 24, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:181'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:181
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:182'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:182
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:183'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:183
        ('put', 'u32', (1, 0, 128), '15.5.3 config-0-resolvedfeatures-fixed.srl:184'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:184
        ('rep', 5, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:185'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:185
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:186'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:186
        ('rep', 7, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:187'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:187
        ('put', 'u32', (128,), '15.5.3 config-0-resolvedfeatures-fixed.srl:188'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:188
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:189'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:189
        ('put', 'f32', (1.875,), '15.5.3 config-0-resolvedfeatures-fixed.srl:190'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:190
        ('put', 'u32', (0, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:191'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:191
        ('put', 'f64', (-1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:192'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:192
        ('rep', 40, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:193'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:193
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:194'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:194
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:195'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:195
        ('put', 'f64', (('$', 'planes.right.hu'), ('=', '-$planes.right.hu'), ('$', 'planes.right.hv'), ('=', '-$planes.right.hv')), '15.5.3 config-0-resolvedfeatures-fixed.srl:196'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:196
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:197'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:197
        ('put', 'i32', (-4, -4), '15.5.3 config-0-resolvedfeatures-fixed.srl:198'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:198
        ('put', 'u8', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:199'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:199
        ('put', 'f64', (0.0, ('$', 'model.centre.1'), ('$', 'model.centre.2')), '15.5.3 config-0-resolvedfeatures-fixed.srl:200'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:200
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:201'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:201
        ('rep', 12, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:202'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:202
        ('class', 'moOriginProfileFeature_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:203'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:203
        ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
        ('put', 'cstr', ('Origin',), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
        ('put', 'u32', (0, 3221225472, 5, 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
        ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
        ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
        ('put', 'u16', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:205'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:205
        ('if', ('$', 'model.solid'), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (('=', '$fixed.id_base+10'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.origin.time//4294967296'), ('=', '$fixed.origin.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), (  # spec 15.4.2 config-0-macros.srl:54
            ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
            ('put', 'u32', (101, 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
            ('put', 'u32', (('=', '17000*0'), ('=', '2024016*0')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
            ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
            ('put', 'f64', (0.0,), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
            ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
            ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
            ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
            ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
            ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
            ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
            ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
            ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
            ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
            ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
            ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
            ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
            ('put', 'u32', (('=', '$fixed.origin.time//4294967296'), ('=', '$fixed.origin.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
            ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
            ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
        ), '15.4.2 config-0-macros.srl:54'),  # spec 15.4.2 config-0-macros.srl:54
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:207'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:207
        ('rep', 14, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:208'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:208
        ('class', 'sgSketch', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:209'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:209
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:210'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:210
        ('rep', 2, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:211'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:211
        ('put', 'u32', (('$', 'model.origin_refs'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:212'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:212
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:213'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:213
        ('put', 'u32', (2097151,), '15.5.3 config-0-resolvedfeatures-fixed.srl:214'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:214
        ('put', 'u8', (3,), '15.5.3 config-0-resolvedfeatures-fixed.srl:215'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:215
        ('put', 'i32', (-1, -1), '15.5.3 config-0-resolvedfeatures-fixed.srl:216'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:216
        ('put', 'f32', (-1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:217'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:217
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:218'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:218
        ('put', 'u16', (0, 4, 2), '15.5.3 config-0-resolvedfeatures-fixed.srl:219'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:219
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:220'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:220
        ('put', 'f32', (-1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:221'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:221
        ('rep', 2, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:222'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:222
        ('put', 'u32', (4,), '15.5.3 config-0-resolvedfeatures-fixed.srl:223'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:223
        ('put', 'u32', (('$', 'model.origin_refs'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:224'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:224
        ('rep', 3, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:225'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:225
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:226'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:226
        ('put', 'u32', (0, 0, 31), '15.5.3 config-0-resolvedfeatures-fixed.srl:227'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:227
        ('rep', 14, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:228'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:228
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:229'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:229
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:230'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:230
        ('put', 'i32', (-2,), '15.5.3 config-0-resolvedfeatures-fixed.srl:231'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:231
        ('rep', 92, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:232'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:232
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:233'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:233
        ('rep', 6, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:234'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:234
        ('put', 'i32', (-1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:235'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:235
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:236'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:236
        ('put', 'u32', (17, 2), '15.5.3 config-0-resolvedfeatures-fixed.srl:237'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:237
        ('rep', 2, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:238'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:238
        ('put', 'u32', (65534,), '15.5.3 config-0-resolvedfeatures-fixed.srl:239'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:239
        ('class', 'sgPointHandle', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:240'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:240
        ('put', 'i32', (-65536,), '15.5.3 config-0-resolvedfeatures-fixed.srl:241'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:241
        ('put', 'u32', (65535,), '15.5.3 config-0-resolvedfeatures-fixed.srl:242'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:242
        ('rep', 16, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:243'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:243
        ('class', 'suObList', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:244'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:244
        ('rep', 14, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:245'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:245
        ('put', 'u32', (65538,), '15.5.3 config-0-resolvedfeatures-fixed.srl:246'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:246
        ('put', 'u32', (('=', '1+$model.origin_refs'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:247'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:247
        ('put', 'u32', (2, 1, 1, 1, 1, 1, 1, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:248'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:248
        ('put', 'u32', (1, 1, 1, 1, 1, 0, 1, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:249'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:249
        ('put', 'u32', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:250'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:250
        ('put', 'cstr', ('',), '15.5.3 config-0-resolvedfeatures-fixed.srl:251'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:251
        ('put', 'u32', (65535,), '15.5.3 config-0-resolvedfeatures-fixed.srl:252'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:252
        ('put', 'i32', (-16512,), '15.5.3 config-0-resolvedfeatures-fixed.srl:253'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:253
        ('put', 'u32', (131071,), '15.5.3 config-0-resolvedfeatures-fixed.srl:254'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:254
        ('put', 'i32', (-65536,), '15.5.3 config-0-resolvedfeatures-fixed.srl:255'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:255
        ('put', 'u32', (65535,), '15.5.3 config-0-resolvedfeatures-fixed.srl:256'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:256
        ('rep', 22, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:257'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:257
        ('put', 'u32', (1,), '15.5.3 config-0-resolvedfeatures-fixed.srl:258'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:258
        ('rep', 32, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:259'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:259
        ('class', 'suObList', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:260'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:260
        ('rep', 40, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:261'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:261
        ('put', 'u32', (3, 1), '15.5.3 config-0-resolvedfeatures-fixed.srl:262'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:262
        ('rep', 7, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:263'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:263
        ('put', 'u32', (100000, 0), '15.5.3 config-0-resolvedfeatures-fixed.srl:264'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:264
        ('class', 'moCompRefPlane_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:265'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:265
        ('class', 'moUnitComponent_c', 1, None, '15.5.3 config-0-resolvedfeatures-fixed.srl:266'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:266
        ('put', 'u32', (2,), '15.5.3 config-0-resolvedfeatures-fixed.srl:267'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:267
        ('rep', 39, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:268'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:268
        ('put', 'i32', (-1, -1, -1, -1), '15.5.3 config-0-resolvedfeatures-fixed.srl:269'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:269
        ('rep', 20, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:270'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:270
        ('put', 'u32', (17000, 2), '15.5.3 config-0-resolvedfeatures-fixed.srl:271'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:271
        ('put', 'u32', (('$', 'tpl.unix'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:272'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:272
        ('rep', 2, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:273'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:273
        ('put', 'u32', (3,), '15.5.3 config-0-resolvedfeatures-fixed.srl:274'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:274
        ('rep', 25, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:275'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:275
        ('put', 'f64', (1.0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:276'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:276
        ('rep', 3, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:277'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:277
        ('put', 'u32', (4,), '15.5.3 config-0-resolvedfeatures-fixed.srl:278'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:278
        ('put', 'i32', (-7,), '15.5.3 config-0-resolvedfeatures-fixed.srl:279'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:279
        ('put', 'u32', (0,), '15.5.3 config-0-resolvedfeatures-fixed.srl:280'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:280
        ('put', 'u32', (('$', 'fixed.origin.regen'),), '15.5.3 config-0-resolvedfeatures-fixed.srl:281'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:281
        ('rep', 12, 0, '15.5.3 config-0-resolvedfeatures-fixed.srl:282'),  # spec 15.5.3 config-0-resolvedfeatures-fixed.srl:282
        ('for', 'f', ('$', 'features'), False, (  # spec 15.5.6 config-0-resolvedfeatures.srl:12
            ('if', ('$', 'f.sketch'), (  # spec 15.5.6 config-0-resolvedfeatures.srl:13
                ('class', 'moProfileFeature_c', 1, ('$', 'f.name'), '15.5.7 config-0-resolvedfeatures-sketch.srl:7'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:7
                ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
                ('put', 'cstr', (('$', 'f.name'),), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
                ('put', 'u32', (0, 1073741824, ('$', 'f.id'), 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
                ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
                ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
                ('put', 'u16', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:9'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:9
                ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
                ('put', 'u32', (('=', '$fixed.id_base+11+$f_index'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
                ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
                ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
                ('put', 'f64', (('$', 'f.cache_memo'),), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
                ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
                ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
                ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
                ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
                ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
                ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
                ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
                ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
                ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
                ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
                ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
                ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
                ('put', 'u32', (('=', '$f.time//4294967296'), ('=', '$f.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
                ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
                ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
                ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:11'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:11
                ('rep', 14, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:12'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:12
                ('class', 'sgSketch', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:13'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:13
                ('put', 'u32', (('=', '4+int($f.at_origin)'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:14'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:14
                ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:15'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:15
                ('put', 'u32', (1, 2097151), '15.5.7 config-0-macros.srl:65'),  # spec 15.5.7 config-0-macros.srl:65
                ('put', 'u8', (3,), '15.5.7 config-0-macros.srl:66'),  # spec 15.5.7 config-0-macros.srl:66
                ('put', 'i32', (-1, -1), '15.5.7 config-0-macros.srl:67'),  # spec 15.5.7 config-0-macros.srl:67
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:68'),  # spec 15.5.7 config-0-macros.srl:68
                ('put', 'u32', (('=', 'int($f.at_origin)'),), '15.5.7 config-0-macros.srl:69'),  # spec 15.5.7 config-0-macros.srl:69
                ('put', 'u16', (0, ('=', '5-int($f.at_origin)'), ('=', '1+int($f.at_origin)')), '15.5.7 config-0-macros.srl:70'),  # spec 15.5.7 config-0-macros.srl:70
                ('put', 'u32', (1,), '15.5.7 config-0-macros.srl:71'),  # spec 15.5.7 config-0-macros.srl:71
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:72'),  # spec 15.5.7 config-0-macros.srl:72
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:73'),  # spec 15.5.7 config-0-macros.srl:73
                ('put', 'u32', (4,), '15.5.7 config-0-macros.srl:74'),  # spec 15.5.7 config-0-macros.srl:74
                ('rep', 7, 0, '15.5.7 config-0-macros.srl:75'),  # spec 15.5.7 config-0-macros.srl:75
                ('put', 'f64', (1.0, 0.0), '15.5.7 config-0-macros.srl:76'),  # spec 15.5.7 config-0-macros.srl:76
                ('put', 'u16', (30,), '15.5.7 config-0-macros.srl:77'),  # spec 15.5.7 config-0-macros.srl:77
                ('put', 'f64', (('$', 'f.corners.0'), ('$', 'f.corners.1')), '15.5.7 config-0-macros.srl:78'),  # spec 15.5.7 config-0-macros.srl:78
                ('put', 'u16', (0, 2), '15.5.7 config-0-macros.srl:79'),  # spec 15.5.7 config-0-macros.srl:79
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:84'),  # spec 15.5.7 config-0-macros.srl:84
                ('put', 'u16', (1,), '15.5.7 config-0-macros.srl:85'),  # spec 15.5.7 config-0-macros.srl:85
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:86'),  # spec 15.5.7 config-0-macros.srl:86
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:87'),  # spec 15.5.7 config-0-macros.srl:87
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:92'),  # spec 15.5.7 config-0-macros.srl:92
                ('put', 'u16', (2,), '15.5.7 config-0-macros.srl:93'),  # spec 15.5.7 config-0-macros.srl:93
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:94'),  # spec 15.5.7 config-0-macros.srl:94
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:95'),  # spec 15.5.7 config-0-macros.srl:95
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:96'),  # spec 15.5.7 config-0-macros.srl:96
                ('put', 'i32', (-2,), '15.5.7 config-0-macros.srl:97'),  # spec 15.5.7 config-0-macros.srl:97
                ('rep', 42, 0, '15.5.7 config-0-macros.srl:98'),  # spec 15.5.7 config-0-macros.srl:98
                ('put', 'u32', (2, 2097151), '15.5.7 config-0-macros.srl:65'),  # spec 15.5.7 config-0-macros.srl:65
                ('put', 'u8', (3,), '15.5.7 config-0-macros.srl:66'),  # spec 15.5.7 config-0-macros.srl:66
                ('put', 'i32', (-1, -1), '15.5.7 config-0-macros.srl:67'),  # spec 15.5.7 config-0-macros.srl:67
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:68'),  # spec 15.5.7 config-0-macros.srl:68
                ('put', 'u32', (('=', '0'),), '15.5.7 config-0-macros.srl:69'),  # spec 15.5.7 config-0-macros.srl:69
                ('put', 'u16', (0, ('=', '5-0'), ('=', '1+0')), '15.5.7 config-0-macros.srl:70'),  # spec 15.5.7 config-0-macros.srl:70
                ('put', 'u32', (1,), '15.5.7 config-0-macros.srl:71'),  # spec 15.5.7 config-0-macros.srl:71
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:72'),  # spec 15.5.7 config-0-macros.srl:72
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:73'),  # spec 15.5.7 config-0-macros.srl:73
                ('put', 'u32', (4,), '15.5.7 config-0-macros.srl:74'),  # spec 15.5.7 config-0-macros.srl:74
                ('rep', 7, 0, '15.5.7 config-0-macros.srl:75'),  # spec 15.5.7 config-0-macros.srl:75
                ('put', 'f64', (1.0, 0.0), '15.5.7 config-0-macros.srl:76'),  # spec 15.5.7 config-0-macros.srl:76
                ('put', 'u16', (30,), '15.5.7 config-0-macros.srl:77'),  # spec 15.5.7 config-0-macros.srl:77
                ('put', 'f64', (('$', 'f.corners.2'), ('$', 'f.corners.3')), '15.5.7 config-0-macros.srl:78'),  # spec 15.5.7 config-0-macros.srl:78
                ('put', 'u16', (0, 2), '15.5.7 config-0-macros.srl:79'),  # spec 15.5.7 config-0-macros.srl:79
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:84'),  # spec 15.5.7 config-0-macros.srl:84
                ('put', 'u16', (3,), '15.5.7 config-0-macros.srl:85'),  # spec 15.5.7 config-0-macros.srl:85
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:86'),  # spec 15.5.7 config-0-macros.srl:86
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:87'),  # spec 15.5.7 config-0-macros.srl:87
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:92'),  # spec 15.5.7 config-0-macros.srl:92
                ('put', 'u16', (4,), '15.5.7 config-0-macros.srl:93'),  # spec 15.5.7 config-0-macros.srl:93
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:94'),  # spec 15.5.7 config-0-macros.srl:94
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:95'),  # spec 15.5.7 config-0-macros.srl:95
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:96'),  # spec 15.5.7 config-0-macros.srl:96
                ('put', 'i32', (-2,), '15.5.7 config-0-macros.srl:97'),  # spec 15.5.7 config-0-macros.srl:97
                ('rep', 42, 0, '15.5.7 config-0-macros.srl:98'),  # spec 15.5.7 config-0-macros.srl:98
                ('put', 'u32', (3, 2097151), '15.5.7 config-0-macros.srl:65'),  # spec 15.5.7 config-0-macros.srl:65
                ('put', 'u8', (3,), '15.5.7 config-0-macros.srl:66'),  # spec 15.5.7 config-0-macros.srl:66
                ('put', 'i32', (-1, -1), '15.5.7 config-0-macros.srl:67'),  # spec 15.5.7 config-0-macros.srl:67
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:68'),  # spec 15.5.7 config-0-macros.srl:68
                ('put', 'u32', (('=', '0'),), '15.5.7 config-0-macros.srl:69'),  # spec 15.5.7 config-0-macros.srl:69
                ('put', 'u16', (0, ('=', '5-0'), ('=', '1+0')), '15.5.7 config-0-macros.srl:70'),  # spec 15.5.7 config-0-macros.srl:70
                ('put', 'u32', (1,), '15.5.7 config-0-macros.srl:71'),  # spec 15.5.7 config-0-macros.srl:71
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:72'),  # spec 15.5.7 config-0-macros.srl:72
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:73'),  # spec 15.5.7 config-0-macros.srl:73
                ('put', 'u32', (4,), '15.5.7 config-0-macros.srl:74'),  # spec 15.5.7 config-0-macros.srl:74
                ('rep', 7, 0, '15.5.7 config-0-macros.srl:75'),  # spec 15.5.7 config-0-macros.srl:75
                ('put', 'f64', (1.0, 0.0), '15.5.7 config-0-macros.srl:76'),  # spec 15.5.7 config-0-macros.srl:76
                ('put', 'u16', (30,), '15.5.7 config-0-macros.srl:77'),  # spec 15.5.7 config-0-macros.srl:77
                ('put', 'f64', (('$', 'f.corners.0'), ('$', 'f.corners.3')), '15.5.7 config-0-macros.srl:78'),  # spec 15.5.7 config-0-macros.srl:78
                ('put', 'u16', (0, 2), '15.5.7 config-0-macros.srl:79'),  # spec 15.5.7 config-0-macros.srl:79
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:84'),  # spec 15.5.7 config-0-macros.srl:84
                ('put', 'u16', (2,), '15.5.7 config-0-macros.srl:85'),  # spec 15.5.7 config-0-macros.srl:85
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:86'),  # spec 15.5.7 config-0-macros.srl:86
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:87'),  # spec 15.5.7 config-0-macros.srl:87
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:92'),  # spec 15.5.7 config-0-macros.srl:92
                ('put', 'u16', (3,), '15.5.7 config-0-macros.srl:93'),  # spec 15.5.7 config-0-macros.srl:93
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:94'),  # spec 15.5.7 config-0-macros.srl:94
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:95'),  # spec 15.5.7 config-0-macros.srl:95
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:96'),  # spec 15.5.7 config-0-macros.srl:96
                ('put', 'i32', (-2,), '15.5.7 config-0-macros.srl:97'),  # spec 15.5.7 config-0-macros.srl:97
                ('rep', 42, 0, '15.5.7 config-0-macros.srl:98'),  # spec 15.5.7 config-0-macros.srl:98
                ('put', 'u32', (4, 2097151), '15.5.7 config-0-macros.srl:65'),  # spec 15.5.7 config-0-macros.srl:65
                ('put', 'u8', (3,), '15.5.7 config-0-macros.srl:66'),  # spec 15.5.7 config-0-macros.srl:66
                ('put', 'i32', (-1, -1), '15.5.7 config-0-macros.srl:67'),  # spec 15.5.7 config-0-macros.srl:67
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:68'),  # spec 15.5.7 config-0-macros.srl:68
                ('put', 'u32', (('=', '0'),), '15.5.7 config-0-macros.srl:69'),  # spec 15.5.7 config-0-macros.srl:69
                ('put', 'u16', (0, ('=', '5-0'), ('=', '1+0')), '15.5.7 config-0-macros.srl:70'),  # spec 15.5.7 config-0-macros.srl:70
                ('put', 'u32', (1,), '15.5.7 config-0-macros.srl:71'),  # spec 15.5.7 config-0-macros.srl:71
                ('put', 'f32', (-1,), '15.5.7 config-0-macros.srl:72'),  # spec 15.5.7 config-0-macros.srl:72
                ('put', 'u16', (0,), '15.5.7 config-0-macros.srl:73'),  # spec 15.5.7 config-0-macros.srl:73
                ('put', 'u32', (4,), '15.5.7 config-0-macros.srl:74'),  # spec 15.5.7 config-0-macros.srl:74
                ('rep', 7, 0, '15.5.7 config-0-macros.srl:75'),  # spec 15.5.7 config-0-macros.srl:75
                ('put', 'f64', (1.0, 0.0), '15.5.7 config-0-macros.srl:76'),  # spec 15.5.7 config-0-macros.srl:76
                ('put', 'u16', (30,), '15.5.7 config-0-macros.srl:77'),  # spec 15.5.7 config-0-macros.srl:77
                ('put', 'f64', (('$', 'f.corners.2'), ('$', 'f.corners.1')), '15.5.7 config-0-macros.srl:78'),  # spec 15.5.7 config-0-macros.srl:78
                ('put', 'u16', (0, 2), '15.5.7 config-0-macros.srl:79'),  # spec 15.5.7 config-0-macros.srl:79
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-macros.srl:84'),  # spec 15.5.7 config-0-macros.srl:84
                ('put', 'u16', (1,), '15.5.7 config-0-macros.srl:85'),  # spec 15.5.7 config-0-macros.srl:85
                ('put', 'i32', (-1,), '15.5.7 config-0-macros.srl:86'),  # spec 15.5.7 config-0-macros.srl:86
                ('put', 'u32', (0,), '15.5.7 config-0-macros.srl:87'),  # spec 15.5.7 config-0-macros.srl:87
                ('if', ('$', 'f.at_origin'), (  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:27
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:30'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:30
                    ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:31'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:31
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:32'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:32
                    ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:33'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:33
                    ('put', 'u16', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:34'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:34
                    ('put', 'i32', (-2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:35'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:35
                    ('rep', 36, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:36'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:36
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:37'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:37
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:38'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:38
                    ('put', 'u32', (5,), '15.5.7 config-0-resolvedfeatures-sketch.srl:39'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:39
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:40'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:40
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:41'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:41
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:42'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:42
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:43'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:43
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:44'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:44
                    ('put', 'u16', (0, 4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:45'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:45
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:46'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:46
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:47'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:47
                    ('class', 'sgExtEnt_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:48'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:48
                    ('class', 'moSketchExtRef_w', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:49'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:49
                    ('class', 'moCompSketchEntHandle_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:50'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:50
                    ('class', 'moUnitComponent_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:51'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:51
                    ('put', 'u32', (2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:52'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:52
                    ('rep', 11, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:53'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:53
                    ('put', 'u32', (10001,), '15.5.7 config-0-resolvedfeatures-sketch.srl:54'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:54
                    ('rep', 24, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:55'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:55
                    ('put', 'i32', (-1, -1, -1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:56'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:56
                    ('rep', 20, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:57'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:57
                    ('put', 'u32', (17000, 5), '15.5.7 config-0-resolvedfeatures-sketch.srl:58'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:58
                    ('put', 'u32', (('$', 'tpl.unix'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:59'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:59
                    ('class', 'sgPointHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:60'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:60
                    ('put', 'i32', (-65536,), '15.5.7 config-0-resolvedfeatures-sketch.srl:61'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:61
                    ('put', 'u32', (65535,), '15.5.7 config-0-resolvedfeatures-sketch.srl:62'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:62
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:63'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:63
                    ('put', 'u32', (1, 0, 0), '15.5.7 config-0-resolvedfeatures-sketch.srl:64'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:64
                    ('put', 'u32', (('=', '$fixed.id_base+10'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:65'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:65
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:66'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:66
                    ('put', 'i32', (-12345, -12345, -12345), '15.5.7 config-0-resolvedfeatures-sketch.srl:67'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:67
                    ('put', 'u32', (0, 17000), '15.5.7 config-0-resolvedfeatures-sketch.srl:68'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:68
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:69'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:69
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:70'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:70
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:71'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:71
                    ('class', 'moPointBackedUpData_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:72'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:72
                    ('rep', 30, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:73'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:73
                    ('put', 'cstr', ('Point1@Origin',), '15.5.7 config-0-resolvedfeatures-sketch.srl:74'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:74
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:75'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:75
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:76'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:76
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:77'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:77
                    ('put', 'u32', (0, 0, 30), '15.5.7 config-0-resolvedfeatures-sketch.srl:78'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:78
                    ('rep', 14, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:79'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:79
                    ('put', 'u32', (6,), '15.5.7 config-0-resolvedfeatures-sketch.srl:80'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:80
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:81'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:81
                    ('put', 'i32', (-2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:82'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:82
                    ('rep', 36, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:83'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:83
                    ('put', 'u32', (5,), '15.5.7 config-0-resolvedfeatures-sketch.srl:84'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:84
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:85'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:85
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:86'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:86
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:87'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:87
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:88'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:88
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:89'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:89
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:90'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:90
                    ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:91'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:91
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:92'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:92
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:93'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:93
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:94'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:94
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:95'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:95
                    ('put', 'u32', (5,), '15.5.7 config-0-resolvedfeatures-sketch.srl:96'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:96
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:97'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:97
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:98'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:98
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:99'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:99
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:100'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:100
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:101'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:101
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:102'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:102
                    ('put', 'u32', (0, 1, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:103'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:103
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:104'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:104
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:105'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:105
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:106'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:106
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:107'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:107
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:108'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:108
                    ('put', 'u16', (0, 4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:109'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:109
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:110'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:110
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:111'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:111
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:112'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:112
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:113'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:113
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:114'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:114
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:115'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:115
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:116'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:116
                    ('put', 'u32', (65539,), '15.5.7 config-0-resolvedfeatures-sketch.srl:117'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:117
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:118'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:118
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:119'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:119
                    ('put', 'u32', (0, 4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:120'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:120
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:121'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:121
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:122'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:122
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:123'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:123
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:124'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:124
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:125'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:125
                    ('put', 'u16', (0, 4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:126'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:126
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:127'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:127
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:128'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:128
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:129'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:129
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:130'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:130
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:131'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:131
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:132'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:132
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:133'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:133
                    ('put', 'u32', (65538,), '15.5.7 config-0-resolvedfeatures-sketch.srl:134'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:134
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:135'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:135
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:136'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:136
                    ('put', 'u32', (0, 3, 3), '15.5.7 config-0-resolvedfeatures-sketch.srl:137'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:137
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:138'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:138
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:139'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:139
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:140'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:140
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:141'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:141
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:142'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:142
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:143'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:143
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:144'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:144
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:145'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:145
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:146'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:146
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:147'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:147
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:148'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:148
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:149'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:149
                    ('put', 'u32', (0, 0, 65538, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:150'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:150
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:151'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:151
                    ('put', 'u32', (0, 2, 4), '15.5.7 config-0-resolvedfeatures-sketch.srl:152'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:152
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:153'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:153
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:154'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:154
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:155'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:155
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:156'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:156
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:157'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:157
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:158'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:158
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:159'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:159
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:160'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:160
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:161'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:161
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:162'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:162
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:163'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:163
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:164'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:164
                    ('put', 'u32', (0, 0, 65539, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:165'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:165
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:166'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:166
                    ('rep', 54, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:167'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:167
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:168'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:168
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:169'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:169
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:170'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:170
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:171'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:171
                    ('put', 'u32', (5, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:172'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:172
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:173'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:173
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:174'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:174
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:175'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:175
                    ('put', 'u16', (2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:176'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:176
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:177'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:177
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:178'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:178
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:179'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:179
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:180'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:180
                    ('put', 'u32', (4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:181'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:181
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:182'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:182
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:183'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:183
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:184'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:184
                    ('put', 'u16', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:185'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:185
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:186'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:186
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:187'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:187
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:188'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:188
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:189'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:189
                    ('put', 'u32', (5, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:190'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:190
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:191'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:191
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:192'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:192
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:193'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:193
                    ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:194'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:194
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:195'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:195
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:196'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:196
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:197'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:197
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:198'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:198
                    ('put', 'u32', (4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:199'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:199
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:200'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:200
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:201'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:201
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:202'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:202
                    ('put', 'u16', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:203'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:203
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:204'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:204
                    ('put', 'u32', (0, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:205'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:205
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:206'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:206
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:207'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:207
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:208'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:208
                    ('put', 'u32', (9, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:209'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:209
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:210'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:210
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:211'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:211
                    ('class', 'sgPointHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:212'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:212
                    ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:213'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:213
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:214'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:214
                    ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:215'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:215
                    ('class', 'sgPointHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:216'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:216
                    ('put', 'i32', (-65536,), '15.5.7 config-0-resolvedfeatures-sketch.srl:217'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:217
                    ('put', 'u32', (65535,), '15.5.7 config-0-resolvedfeatures-sketch.srl:218'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:218
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:219'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:219
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:220'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:220
                    ('rep', 36, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:221'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:221
                ), (  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:27
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:224'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:224
                    ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:225'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:225
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:226'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:226
                    ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:227'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:227
                    ('put', 'u16', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:228'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:228
                    ('put', 'i32', (-2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:229'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:229
                    ('rep', 36, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:230'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:230
                    ('put', 'u32', (5,), '15.5.7 config-0-resolvedfeatures-sketch.srl:231'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:231
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:232'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:232
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:233'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:233
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:234'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:234
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:235'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:235
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:236'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:236
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:237'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:237
                    ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:238'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:238
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:239'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:239
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:240'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:240
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:241'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:241
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:242'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:242
                    ('put', 'u32', (5,), '15.5.7 config-0-resolvedfeatures-sketch.srl:243'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:243
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:244'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:244
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:245'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:245
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:246'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:246
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:247'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:247
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:248'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:248
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:249'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:249
                    ('put', 'u32', (0, 1, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:250'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:250
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:251'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:251
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:252'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:252
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:253'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:253
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:254'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:254
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:255'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:255
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:256'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:256
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:257'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:257
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:258'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:258
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:259'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:259
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:260'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:260
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:261'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:261
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:262'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:262
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:263'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:263
                    ('put', 'u32', (65539,), '15.5.7 config-0-resolvedfeatures-sketch.srl:264'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:264
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:265'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:265
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:266'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:266
                    ('put', 'u32', (0, 4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:267'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:267
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:268'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:268
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:269'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:269
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:270'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:270
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:271'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:271
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:272'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:272
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:273'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:273
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:274'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:274
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:275'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:275
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:276'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:276
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:277'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:277
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:278'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:278
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:279'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:279
                    ('rep', 10, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:280'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:280
                    ('put', 'u32', (65538,), '15.5.7 config-0-resolvedfeatures-sketch.srl:281'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:281
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:282'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:282
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:283'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:283
                    ('put', 'u32', (0, 3, 3), '15.5.7 config-0-resolvedfeatures-sketch.srl:284'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:284
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:285'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:285
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:286'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:286
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:287'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:287
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:288'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:288
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:289'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:289
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:290'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:290
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:291'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:291
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:292'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:292
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:293'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:293
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:294'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:294
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:295'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:295
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:296'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:296
                    ('put', 'u32', (0, 0, 65538, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:297'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:297
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:298'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:298
                    ('put', 'u32', (0, 2, 4), '15.5.7 config-0-resolvedfeatures-sketch.srl:299'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:299
                    ('put', 'u32', (2097151,), '15.5.7 config-0-resolvedfeatures-sketch.srl:300'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:300
                    ('put', 'u8', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:301'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:301
                    ('put', 'i32', (-1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:302'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:302
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:303'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:303
                    ('put', 'u32', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:304'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:304
                    ('put', 'u16', (0, 5, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:305'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:305
                    ('put', 'u32', (65537,), '15.5.7 config-0-resolvedfeatures-sketch.srl:306'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:306
                    ('put', 'f32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:307'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:307
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:308'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:308
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:309'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:309
                    ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:310'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:310
                    ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:311'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:311
                    ('put', 'u32', (0, 0, 65539, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:312'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:312
                    ('put', 'f64', (-1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:313'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:313
                    ('rep', 54, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:314'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:314
                    ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:315'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:315
                    ('rep', 6, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:316'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:316
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:317'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:317
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:318'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:318
                    ('put', 'u32', (5, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:319'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:319
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:320'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:320
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:321'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:321
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:322'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:322
                    ('put', 'u16', (2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:323'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:323
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:324'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:324
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:325'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:325
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:326'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:326
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:327'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:327
                    ('put', 'u32', (4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:328'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:328
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:329'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:329
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:330'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:330
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:331'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:331
                    ('put', 'u16', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:332'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:332
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:333'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:333
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:334'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:334
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:335'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:335
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:336'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:336
                    ('put', 'u32', (5, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:337'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:337
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:338'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:338
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:339'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:339
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:340'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:340
                    ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:341'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:341
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:342'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:342
                    ('rep', 12, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:343'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:343
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:344'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:344
                    ('rep', 16, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:345'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:345
                    ('put', 'u32', (4, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:346'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:346
                    ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:347'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:347
                    ('put', 'u32', (65534,), '15.5.7 config-0-resolvedfeatures-sketch.srl:348'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:348
                    ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:349'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:349
                    ('put', 'u16', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:350'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:350
                    ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:351'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:351
                    ('rep', 18, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:352'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:352
                ), '15.5.7 config-0-resolvedfeatures-sketch.srl:27'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:27
                ('class', 'suObList', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:354'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:354
                ('rep', 14, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:355'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:355
                ('put', 'u32', (65537, 5), '15.5.7 config-0-resolvedfeatures-sketch.srl:356'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:356
                ('put', 'u32', (('=', '5+int($f.at_origin)'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:357'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:357
                ('put', 'u32', (5, 1, 1, 1, 1, 1, 1, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:358'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:358
                ('put', 'u32', (1, 1, 1, 1, 0, 1, 0, 0), '15.5.7 config-0-resolvedfeatures-sketch.srl:359'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:359
                ('put', 'cstr', ('',), '15.5.7 config-0-resolvedfeatures-sketch.srl:360'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:360
                ('put', 'u32', (65535,), '15.5.7 config-0-resolvedfeatures-sketch.srl:361'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:361
                ('put', 'i32', (-16512,), '15.5.7 config-0-resolvedfeatures-sketch.srl:362'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:362
                ('put', 'u32', (131071,), '15.5.7 config-0-resolvedfeatures-sketch.srl:363'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:363
                ('put', 'i32', (-65536,), '15.5.7 config-0-resolvedfeatures-sketch.srl:364'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:364
                ('put', 'u32', (65535,), '15.5.7 config-0-resolvedfeatures-sketch.srl:365'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:365
                ('rep', 22, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:366'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:366
                ('put', 'u32', (10,), '15.5.7 config-0-resolvedfeatures-sketch.srl:367'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:367
                ('rep', 32, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:368'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:368
                ('class', 'suObList', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:369'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:369
                ('hex', '01', '15.5.7 config-0-resolvedfeatures-sketch.srl:370'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:370
                ('put', 'u8', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:371'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:371
                ('class', 'moSketchRegion_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:372'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:372
                ('class', 'suObList', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:373'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:373
                ('hex', '04', '15.5.7 config-0-resolvedfeatures-sketch.srl:374'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:374
                ('put', 'u8', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:375'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:375
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:376'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:376
                ('put', 'u16', (2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:377'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:377
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:378'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:378
                ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:379'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:379
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:380'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:380
                ('put', 'u16', (1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:381'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:381
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:382'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:382
                ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:383'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:383
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:384'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:384
                ('put', 'u16', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:385'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:385
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:386'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:386
                ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:387'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:387
                ('class', 'sgLineHandle', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:388'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:388
                ('put', 'u16', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:389'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:389
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:390'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:390
                ('rep', 34, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:391'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:391
                ('put', 'u32', (1, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:392'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:392
                ('class', 'moSketchChain_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:393'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:393
                ('put', 'u32', (65540,), '15.5.7 config-0-resolvedfeatures-sketch.srl:394'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:394
                ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:395'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:395
                ('put', 'u32', (2, 3, 4, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:396'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:396
                ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:397'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:397
                ('put', 'u32', (6,), '15.5.7 config-0-resolvedfeatures-sketch.srl:398'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:398
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:399'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:399
                ('put', 'u32', (0, 0, 5, 5), '15.5.7 config-0-resolvedfeatures-sketch.srl:400'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:400
                ('put', 'cstr', ('',), '15.5.7 config-0-resolvedfeatures-sketch.srl:401'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:401
                ('put', 'i32', (-65536,), '15.5.7 config-0-resolvedfeatures-sketch.srl:402'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:402
                ('put', 'u32', (65535,), '15.5.7 config-0-resolvedfeatures-sketch.srl:403'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:403
                ('rep', 18, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:404'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:404
                ('put', 'u32', (3, 1), '15.5.7 config-0-resolvedfeatures-sketch.srl:405'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:405
                ('rep', 7, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:406'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:406
                ('put', 'u32', (100000, 0), '15.5.7 config-0-resolvedfeatures-sketch.srl:407'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:407
                ('class', 'moCompRefPlane_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:408'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:408
                ('class', 'moUnitComponent_c', 1, None, '15.5.7 config-0-resolvedfeatures-sketch.srl:409'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:409
                ('put', 'u32', (2,), '15.5.7 config-0-resolvedfeatures-sketch.srl:410'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:410
                ('rep', 39, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:411'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:411
                ('put', 'i32', (-1, -1, -1, -1), '15.5.7 config-0-resolvedfeatures-sketch.srl:412'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:412
                ('rep', 20, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:413'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:413
                ('put', 'u32', (17000, 2), '15.5.7 config-0-resolvedfeatures-sketch.srl:414'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:414
                ('put', 'u32', (('$', 'tpl.unix'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:415'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:415
                ('rep', 2, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:416'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:416
                ('put', 'u32', (3,), '15.5.7 config-0-resolvedfeatures-sketch.srl:417'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:417
                ('rep', 25, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:418'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:418
                ('put', 'f64', (1.0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:419'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:419
                ('rep', 3, 0, '15.5.7 config-0-resolvedfeatures-sketch.srl:420'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:420
                ('put', 'u32', (4,), '15.5.7 config-0-resolvedfeatures-sketch.srl:421'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:421
                ('put', 'i32', (-1,), '15.5.7 config-0-resolvedfeatures-sketch.srl:422'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:422
                ('put', 'u32', (0,), '15.5.7 config-0-resolvedfeatures-sketch.srl:423'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:423
                ('put', 'u32', (('$', 'f.regen'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:424'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:424
                ('put', 'u32', (('=', '$f_index+1'),), '15.5.7 config-0-resolvedfeatures-sketch.srl:425'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:425
                ('put', 'u32', (0, 0), '15.5.7 config-0-resolvedfeatures-sketch.srl:426'),  # spec 15.5.7 config-0-resolvedfeatures-sketch.srl:426
            ), (  # spec 15.5.6 config-0-resolvedfeatures.srl:13
                ('if', ('$', 'f.first'), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:6
                    ('class', 'moExtrusion_c', 1, ('$', 'f.name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:7'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:7
                    ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
                    ('put', 'cstr', (('$', 'f.name'),), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
                    ('put', 'u32', (0, 1073742144, ('$', 'f.id'), 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
                    ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
                    ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
                    ('put', 'u16', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:9'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:9
                    ('objref', ('$', 'f.sketch_name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:10'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:10
                    ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
                    ('put', 'u32', (('=', '$fixed.id_base+11+$f_index'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
                    ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
                    ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
                    ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
                    ('put', 'f64', (('$', 'f.cache_memo'),), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
                    ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
                    ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
                    ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
                    ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
                    ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
                    ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
                    ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
                    ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
                    ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
                    ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
                    ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
                    ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
                    ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
                    ('put', 'u32', (('=', '$f.time//4294967296'), ('=', '$f.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
                    ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
                    ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:12'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:12
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:13'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:13
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:14'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:14
                    ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:15'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:15
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:16'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:16
                    ('objref', ('$', 'f.body_label'), '15.5.8 config-0-resolvedfeatures-extrude.srl:17'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:17
                    ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:18'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:18
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:19'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:19
                    ('put', 'u32', (('$', 'f.body_id'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:20'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:20
                    ('put', 'u32', (3, 0, 1, 65537), '15.5.8 config-0-resolvedfeatures-extrude.srl:21'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:21
                    ('class', 'moPerBodyChooserData_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:22'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:22
                    ('hex', '02', '15.5.8 config-0-resolvedfeatures-extrude.srl:23'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:23
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:24'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:24
                    ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:25'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:25
                    ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:26'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:26
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:27'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:27
                    ('put', 'f32', (-253,), '15.5.8 config-0-resolvedfeatures-extrude.srl:28'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:28
                    ('hex', '9425AD49B254', '15.5.8 config-0-resolvedfeatures-extrude.srl:29'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:29
                    ('put', 'u64', (6103021453049119613,), '15.5.8 config-0-resolvedfeatures-extrude.srl:30'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:30
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:31'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:31
                    ('class', 'moEndFaceSurfIdRep_c', 1, 'face_end1', '15.5.8 config-0-resolvedfeatures-extrude.srl:32'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:32
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:33'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:33
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:34'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:34
                    ('class', 'moExtObject_c', 1, 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:35'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:35
                    ('class', 'moCStringHandle_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:36'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:36
                    ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:37'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:37
                    ('class', 'moCStringHandle_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:38'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:38
                    ('put', 'cstr', (('$', 'doc.name'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:39'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:39
                    ('hex', '02', '15.5.8 config-0-resolvedfeatures-extrude.srl:40'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:40
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:41'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:41
                    ('put', 'u32', (('$', 'doc.created'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:42'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:42
                    ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:43'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:43
                    ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:44'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:44
                    ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:45'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:45
                    ('rep', 18, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:46'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:46
                    ('put', 'cstr', ('Default',), '15.5.8 config-0-resolvedfeatures-extrude.srl:47'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:47
                    ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:48'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:48
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:49'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:49
                    ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:50'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:50
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side1', '15.5.8 config-0-resolvedfeatures-extrude.srl:51'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:51
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:52'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:52
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:53'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:53
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:54'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:54
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:55'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:55
                    ('put', 'u32', (4,), '15.5.8 config-0-resolvedfeatures-extrude.srl:56'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:56
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side2', '15.5.8 config-0-resolvedfeatures-extrude.srl:57'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:57
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:58'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:58
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:59'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:59
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:60'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:60
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:61'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:61
                    ('put', 'u32', (3,), '15.5.8 config-0-resolvedfeatures-extrude.srl:62'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:62
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side3', '15.5.8 config-0-resolvedfeatures-extrude.srl:63'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:63
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:64'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:64
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:65'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:65
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:66'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:66
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:67'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:67
                    ('put', 'u32', (2,), '15.5.8 config-0-resolvedfeatures-extrude.srl:68'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:68
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side4', '15.5.8 config-0-resolvedfeatures-extrude.srl:69'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:69
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:70'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:70
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:71'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:71
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:72'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:72
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:73'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:73
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:74'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:74
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:75'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:75
                    ('put', 'u32', (17000, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:76'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:76
                    ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:77'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:77
                    ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:78'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:78
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:79'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:79
                    ('put', 'f32', (-253,), '15.5.8 config-0-resolvedfeatures-extrude.srl:80'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:80
                    ('hex', '9425AD49B254', '15.5.8 config-0-resolvedfeatures-extrude.srl:81'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:81
                    ('put', 'u64', (6103021453049119613,), '15.5.8 config-0-resolvedfeatures-extrude.srl:82'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:82
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:83'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:83
                    ('class', 'moEndFaceSurfIdRep_c', 1, 'face_end2', '15.5.8 config-0-resolvedfeatures-extrude.srl:84'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:84
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:85'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:85
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:86'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:86
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:87'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:87
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:88'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:88
                    ('put', 'u32', (1, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:89'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:89
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side5', '15.5.8 config-0-resolvedfeatures-extrude.srl:90'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:90
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:91'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:91
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:92'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:92
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:93'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:93
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:94'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:94
                    ('put', 'u32', (4,), '15.5.8 config-0-resolvedfeatures-extrude.srl:95'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:95
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side6', '15.5.8 config-0-resolvedfeatures-extrude.srl:96'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:96
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:97'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:97
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:98'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:98
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:99'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:99
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:100'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:100
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:101'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:101
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side7', '15.5.8 config-0-resolvedfeatures-extrude.srl:102'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:102
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:103'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:103
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:104'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:104
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:105'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:105
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:106'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:106
                    ('put', 'u32', (2,), '15.5.8 config-0-resolvedfeatures-extrude.srl:107'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:107
                    ('class', 'moFromSktEntSurfIdRep_c', 1, 'side8', '15.5.8 config-0-resolvedfeatures-extrude.srl:108'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:108
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:109'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:109
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:110'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:110
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:111'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:111
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:112'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:112
                    ('put', 'u32', (3,), '15.5.8 config-0-resolvedfeatures-extrude.srl:113'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:113
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:114'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:114
                    ('put', 'u32', (17000,), '15.5.8 config-0-resolvedfeatures-extrude.srl:115'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:115
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:116'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:116
                    ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:117'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:117
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:118'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:118
                ), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:6
                    ('class', 'moICE_c', 1, ('$', 'f.name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:120'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:120
                    ('class', 'moNodeName_c', 1, None, '15.4.2 config-0-macros.srl:18'),  # spec 15.4.2 config-0-macros.srl:18
                    ('put', 'cstr', (('$', 'f.name'),), '15.4.2 config-0-macros.srl:19'),  # spec 15.4.2 config-0-macros.srl:19
                    ('put', 'u32', (0, 1073742144, ('$', 'f.id'), 0), '15.4.2 config-0-macros.srl:11'),  # spec 15.4.2 config-0-macros.srl:11
                    ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:12'),  # spec 15.4.2 config-0-macros.srl:12
                    ('rep', 6, 0, '15.4.2 config-0-macros.srl:13'),  # spec 15.4.2 config-0-macros.srl:13
                    ('put', 'u16', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:122'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:122
                    ('objref', ('$', 'f.sketch_name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:123'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:123
                    ('rep', 12, 0, '15.4.2 config-0-macros.srl:27'),  # spec 15.4.2 config-0-macros.srl:27
                    ('put', 'u32', (('=', '$fixed.id_base+11+$f_index'), 0), '15.4.2 config-0-macros.srl:28'),  # spec 15.4.2 config-0-macros.srl:28
                    ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:29'),  # spec 15.4.2 config-0-macros.srl:29
                    ('put', 'u32', (('=', '17000*1'), ('=', '2024016*1')), '15.4.2 config-0-macros.srl:30'),  # spec 15.4.2 config-0-macros.srl:30
                    ('put', 'u32', (17000,), '15.4.2 config-0-macros.srl:31'),  # spec 15.4.2 config-0-macros.srl:31
                    ('put', 'f64', (('$', 'f.cache_memo'),), '15.4.2 config-0-macros.srl:32'),  # spec 15.4.2 config-0-macros.srl:32
                    ('put', 'u32', (2024016,), '15.4.2 config-0-macros.srl:33'),  # spec 15.4.2 config-0-macros.srl:33
                    ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:34'),  # spec 15.4.2 config-0-macros.srl:34
                    ('put', 'cstr', ('',), '15.4.2 config-0-macros.srl:35'),  # spec 15.4.2 config-0-macros.srl:35
                    ('put', 'u8', (0,), '15.4.2 config-0-macros.srl:36'),  # spec 15.4.2 config-0-macros.srl:36
                    ('put', 'i16', (-1,), '15.4.2 config-0-macros.srl:37'),  # spec 15.4.2 config-0-macros.srl:37
                    ('put', 'u16', (0,), '15.4.2 config-0-macros.srl:38'),  # spec 15.4.2 config-0-macros.srl:38
                    ('put', 'u8', (3,), '15.4.2 config-0-macros.srl:39'),  # spec 15.4.2 config-0-macros.srl:39
                    ('put', 'i32', (-1, -1), '15.4.2 config-0-macros.srl:40'),  # spec 15.4.2 config-0-macros.srl:40
                    ('put', 'f32', (-1,), '15.4.2 config-0-macros.srl:41'),  # spec 15.4.2 config-0-macros.srl:41
                    ('rep', 14, 0, '15.4.2 config-0-macros.srl:42'),  # spec 15.4.2 config-0-macros.srl:42
                    ('put', 'u32', (1,), '15.4.2 config-0-macros.srl:43'),  # spec 15.4.2 config-0-macros.srl:43
                    ('rep', 6, 0, '15.4.2 config-0-macros.srl:44'),  # spec 15.4.2 config-0-macros.srl:44
                    ('put', 'i32', (-1,), '15.4.2 config-0-macros.srl:45'),  # spec 15.4.2 config-0-macros.srl:45
                    ('put', 'u32', (('=', '$f.time//4294967296'), ('=', '$f.time%4294967296')), '15.4.2 config-0-macros.srl:46'),  # spec 15.4.2 config-0-macros.srl:46
                    ('put', 'u16', (2,), '15.4.2 config-0-macros.srl:47'),  # spec 15.4.2 config-0-macros.srl:47
                    ('put', 'u32', (350108,), '15.4.2 config-0-macros.srl:48'),  # spec 15.4.2 config-0-macros.srl:48
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:125'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:125
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:126'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:126
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:127'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:127
                    ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:128'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:128
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:129'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:129
                    ('objref', ('$', 'f.body_label'), '15.5.8 config-0-resolvedfeatures-extrude.srl:130'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:130
                    ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:131'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:131
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:132'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:132
                    ('put', 'u32', (('$', 'f.body_id'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:133'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:133
                    ('put', 'u32', (3, 0, 1, 65537), '15.5.8 config-0-resolvedfeatures-extrude.srl:134'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:134
                    ('class', 'moPerBodyChooserData_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:135'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:135
                    ('hex', '02', '15.5.8 config-0-resolvedfeatures-extrude.srl:136'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:136
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:137'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:137
                    ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:138'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:138
                    ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:139'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:139
                    ('put', 'u32', (('$', 'f.counter_face1'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:140'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:140
                    ('put', 'u64', (6103021453049119613, 6103021453049119613), '15.5.8 config-0-resolvedfeatures-extrude.srl:141'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:141
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:142'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:142
                    ('class', 'moEndFace3IntSurfIdRep_c', 1, 'face_end1', '15.5.8 config-0-resolvedfeatures-extrude.srl:143'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:143
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:144'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:144
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:145'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:145
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:146'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:146
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:147'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:147
                    ('rep', 12, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:148'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:148
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side1', '15.5.8 config-0-resolvedfeatures-extrude.srl:149'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:149
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:150'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:150
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:151'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:151
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:152'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:152
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:153'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:153
                    ('put', 'u32', (4,), '15.5.8 config-0-resolvedfeatures-extrude.srl:154'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:154
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:155'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:155
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:156'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:156
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side2', '15.5.8 config-0-resolvedfeatures-extrude.srl:157'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:157
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:158'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:158
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:159'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:159
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:160'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:160
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:161'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:161
                    ('put', 'u32', (3,), '15.5.8 config-0-resolvedfeatures-extrude.srl:162'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:162
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:163'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:163
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:164'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:164
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side3', '15.5.8 config-0-resolvedfeatures-extrude.srl:165'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:165
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:166'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:166
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:167'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:167
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:168'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:168
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:169'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:169
                    ('put', 'u32', (2,), '15.5.8 config-0-resolvedfeatures-extrude.srl:170'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:170
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:171'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:171
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:172'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:172
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side4', '15.5.8 config-0-resolvedfeatures-extrude.srl:173'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:173
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:174'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:174
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:175'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:175
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:176'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:176
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:177'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:177
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:178'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:178
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:179'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:179
                    ('rep', 14, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:180'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:180
                    ('put', 'u32', (17000, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:181'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:181
                    ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:182'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:182
                    ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:183'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:183
                    ('put', 'u32', (('$', 'f.counter_face2'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:184'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:184
                    ('put', 'u64', (6103021453049119613, 6103021453049119613), '15.5.8 config-0-resolvedfeatures-extrude.srl:185'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:185
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:186'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:186
                    ('class', 'moEndFace3IntSurfIdRep_c', 1, 'face_end2', '15.5.8 config-0-resolvedfeatures-extrude.srl:187'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:187
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:188'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:188
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:189'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:189
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:190'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:190
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:191'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:191
                    ('put', 'u32', (1, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:192'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:192
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side5', '15.5.8 config-0-resolvedfeatures-extrude.srl:193'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:193
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:194'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:194
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:195'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:195
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:196'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:196
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:197'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:197
                    ('put', 'u32', (4,), '15.5.8 config-0-resolvedfeatures-extrude.srl:198'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:198
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:199'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:199
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:200'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:200
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side6', '15.5.8 config-0-resolvedfeatures-extrude.srl:201'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:201
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:202'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:202
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:203'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:203
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:204'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:204
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:205'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:205
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:206'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:206
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:207'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:207
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:208'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:208
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side7', '15.5.8 config-0-resolvedfeatures-extrude.srl:209'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:209
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:210'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:210
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:211'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:211
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:212'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:212
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:213'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:213
                    ('put', 'u32', (2,), '15.5.8 config-0-resolvedfeatures-extrude.srl:214'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:214
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:215'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:215
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:216'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:216
                    ('class', 'moFromSktEnt3IntSurfIdRep_c', 1, 'side8', '15.5.8 config-0-resolvedfeatures-extrude.srl:217'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:217
                    ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:218'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:218
                    ('class', 'moFR_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:219'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:219
                    ('objref', 'ext_obj', '15.5.8 config-0-resolvedfeatures-extrude.srl:220'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:220
                    ('put', 'u32', (('$', 'f.id'), ('$', 'f.created')), '15.5.8 config-0-resolvedfeatures-extrude.srl:221'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:221
                    ('put', 'u32', (3,), '15.5.8 config-0-resolvedfeatures-extrude.srl:222'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:222
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:223'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:223
                    ('rep', 14, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:224'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:224
                    ('put', 'u32', (17000,), '15.5.8 config-0-resolvedfeatures-extrude.srl:225'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:225
                    ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:226'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:226
                    ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:227'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:227
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:228'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:228
                ), '15.5.8 config-0-resolvedfeatures-extrude.srl:6'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:6
                ('class', 'moBBoxCenterData_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:231'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:231
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:232'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:232
                ('put', 'f64', (('$', 'f.centre.0'), ('$', 'f.centre.1'), ('$', 'f.centre.2'), ('$', 'f.diagonal')), '15.5.8 config-0-resolvedfeatures-extrude.srl:233'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:233
                ('rep', 8, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:234'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:234
                ('if', ('$', 'f.merge'), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:235
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:236'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:236
                ), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:235
                ), '15.5.8 config-0-resolvedfeatures-extrude.srl:235'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:235
                ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:238'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:238
                ('objref', ('$', 'f.name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:239'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:239
                ('put', 'u32', (65537,), '15.5.8 config-0-resolvedfeatures-extrude.srl:240'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:240
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:241'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:241
                ('objref', ('$', 'f.name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:242'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:242
                ('put', 'u32', (1, 65537), '15.5.8 config-0-resolvedfeatures-extrude.srl:243'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:243
                ('class', 'moPerBodyChooserData_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:244'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:244
                ('hex', '02', '15.5.8 config-0-resolvedfeatures-extrude.srl:245'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:245
                ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:246'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:246
                ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:247'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:247
                ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:248'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:248
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:249'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:249
                ('put', 'f32', (-253,), '15.5.8 config-0-resolvedfeatures-extrude.srl:250'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:250
                ('hex', '9425AD49B254', '15.5.8 config-0-resolvedfeatures-extrude.srl:251'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:251
                ('put', 'u64', (6103021453049119613,), '15.5.8 config-0-resolvedfeatures-extrude.srl:252'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:252
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:253'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:253
                ('objref', 'face_end1', '15.5.8 config-0-resolvedfeatures-extrude.srl:254'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:254
                ('objref', 'side1', '15.5.8 config-0-resolvedfeatures-extrude.srl:255'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:255
                ('objref', 'side2', '15.5.8 config-0-resolvedfeatures-extrude.srl:256'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:256
                ('objref', 'side3', '15.5.8 config-0-resolvedfeatures-extrude.srl:257'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:257
                ('objref', 'side4', '15.5.8 config-0-resolvedfeatures-extrude.srl:258'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:258
                ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:259'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:259
                ('put', 'u32', (17000, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:260'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:260
                ('class', 'moFaceRef_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:261'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:261
                ('put', 'u32', (1, 0, 6, 768), '15.5.8 config-0-resolvedfeatures-extrude.srl:262'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:262
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:263'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:263
                ('put', 'f32', (-253,), '15.5.8 config-0-resolvedfeatures-extrude.srl:264'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:264
                ('hex', '9425AD49B254', '15.5.8 config-0-resolvedfeatures-extrude.srl:265'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:265
                ('put', 'u64', (6103021453049119613,), '15.5.8 config-0-resolvedfeatures-extrude.srl:266'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:266
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:267'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:267
                ('objref', 'face_end2', '15.5.8 config-0-resolvedfeatures-extrude.srl:268'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:268
                ('objref', 'side5', '15.5.8 config-0-resolvedfeatures-extrude.srl:269'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:269
                ('objref', 'side6', '15.5.8 config-0-resolvedfeatures-extrude.srl:270'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:270
                ('objref', 'side7', '15.5.8 config-0-resolvedfeatures-extrude.srl:271'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:271
                ('objref', 'side8', '15.5.8 config-0-resolvedfeatures-extrude.srl:272'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:272
                ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:273'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:273
                ('put', 'u32', (17000,), '15.5.8 config-0-resolvedfeatures-extrude.srl:274'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:274
                ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:275'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:275
                ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:276'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:276
                ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:277'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:277
                ('class', 'moBBoxCenterData_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:278'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:278
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:279'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:279
                ('put', 'f64', (('$', 'f.centre.0'), ('$', 'f.centre.1'), ('$', 'f.centre.2'), ('$', 'f.diagonal')), '15.5.8 config-0-resolvedfeatures-extrude.srl:280'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:280
                ('rep', 8, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:281'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:281
                ('if', ('$', 'f.merge'), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:282
                    ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:283'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:283
                ), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:282
                ), '15.5.8 config-0-resolvedfeatures-extrude.srl:282'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:282
                ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:285'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:285
                ('objref', ('$', 'f.name'), '15.5.8 config-0-resolvedfeatures-extrude.srl:286'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:286
                ('rep', 10, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:287'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:287
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:288'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:288
                ('class', 'moPMarkRecord_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:289'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:289
                ('put', 'u16', (('$', 'f.counter_marks'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:290'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:290
                ('rep', 64, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:291'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:291
                ('class', 'moEndSpec_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:293'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:293
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:294'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:294
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:295'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:295
                ('rep', 18, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:296'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:296
                ('class', 'moDisplayDistanceDim_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:297'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:297
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:298'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:298
                ('put', 'u32', (65535,), '15.5.8 config-0-resolvedfeatures-extrude.srl:299'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:299
                ('put', 'i32', (-253,), '15.5.8 config-0-resolvedfeatures-extrude.srl:300'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:300
                ('put', 'u32', (255,), '15.5.8 config-0-resolvedfeatures-extrude.srl:301'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:301
                ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:302'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:302
                ('put', 'f32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:303'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:303
                ('rep', 14, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:304'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:304
                ('put', 'u32', (17000, 0, 524416), '15.5.8 config-0-resolvedfeatures-extrude.srl:305'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:305
                ('rep', 83, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:306'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:306
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:307'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:307
                ('put', 'u32', (256, 51200), '15.5.8 config-0-resolvedfeatures-extrude.srl:308'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:308
                ('rep', 20, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:309'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:309
                ('put', 'f64', (-1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:310'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:310
                ('put', 'u32', (0, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:311'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:311
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:312'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:312
                ('put', 'f32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:313'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:313
                ('put', 'u32', (0, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:314'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:314
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:315'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:315
                ('put', 'f32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:316'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:316
                ('rep', 12, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:317'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:317
                ('put', 'i32', (-1, -1), '15.5.8 config-0-resolvedfeatures-extrude.srl:318'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:318
                ('put', 'u32', (0, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:319'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:319
                ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:320'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:320
                ('put', 'f32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:321'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:321
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:322'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:322
                ('put', 'u32', (4,), '15.5.8 config-0-resolvedfeatures-extrude.srl:323'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:323
                ('rep', 96, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:324'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:324
                ('put', 'u32', (2, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:325'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:325
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:326'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:326
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:327'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:327
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:328'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:328
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:329'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:329
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:330'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:330
                ('rep', 24, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:331'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:331
                ('put', 'u32', (18,), '15.5.8 config-0-resolvedfeatures-extrude.srl:332'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:332
                ('rep', 30, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:333'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:333
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:334'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:334
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:335'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:335
                ('put', 'f64', (1e-06, 1e-06), '15.5.8 config-0-resolvedfeatures-extrude.srl:336'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:336
                ('rep', 18, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:337'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:337
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:338'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:338
                ('put', 'u32', (0, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:339'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:339
                ('class', 'moFeatureDimHandle_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:340'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:340
                ('rep', 42, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:341'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:341
                ('put', 'i32', (-1, -1, -1, -1), '15.5.8 config-0-resolvedfeatures-extrude.srl:342'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:342
                ('rep', 20, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:343'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:343
                ('put', 'u32', (17000,), '15.5.8 config-0-resolvedfeatures-extrude.srl:344'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:344
                ('rep', 15, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:345'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:345
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:346'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:346
                ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:347'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:347
                ('class', 'ParallelPlaneDistanceDim_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:348'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:348
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:349'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:349
                ('class', 'moLengthParameter_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:350'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:350
                ('class', 'moNodeName_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:353'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:353
                ('put', 'cstr', ('D1',), '15.5.8 config-0-resolvedfeatures-extrude.srl:354'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:354
                ('put', 'f64', (2.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:355'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:355
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:356'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:356
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:357'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:357
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:358'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:358
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:359'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:359
                ('put', 'f64', (('$', 'f.depth'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:360'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:360
                ('rep', 3, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:361'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:361
                ('put', 'u32', (('=', '$f.sketch_id+1'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:362'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:362
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:363'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:363
                ('put', 'f64', (('$', 'f.corners.2'), ('$', 'f.corners.3')), '15.5.8 config-0-resolvedfeatures-extrude.srl:364'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:364
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:365'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:365
                ('put', 'f64', (('$', 'f.corners.2'), ('$', 'f.corners.3'), ('$', 'f.depth')), '15.5.8 config-0-resolvedfeatures-extrude.srl:366'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:366
                ('rep', 24, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:367'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:367
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:368'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:368
                ('rep', 14, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:369'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:369
                ('put', 'f64', (1.0, 1.0), '15.5.8 config-0-resolvedfeatures-extrude.srl:370'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:370
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:371'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:371
                ('put', 'u32', (65537,), '15.5.8 config-0-resolvedfeatures-extrude.srl:372'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:372
                ('rep', 3, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:373'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:373
                ('put', 'f32', (1.875,), '15.5.8 config-0-resolvedfeatures-extrude.srl:374'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:374
                ('rep', 32, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:375'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:375
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:376'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:376
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:377'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:377
                ('put', 'f64', (-1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:378'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:378
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:379'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:379
                ('put', 'f64', (('=', '-$f.corners.2'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:380'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:380
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:381'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:381
                ('put', 'f64', (('=', '-$f.corners.3'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:382'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:382
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:383'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:383
                ('rep', 3, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:384'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:384
                ('put', 'u32', (65537,), '15.5.8 config-0-resolvedfeatures-extrude.srl:385'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:385
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:386'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:386
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:387'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:387
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:388'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:388
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:389'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:389
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:390'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:390
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:391'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:391
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:392'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:392
                ('put', 'f64', (0.5,), '15.5.8 config-0-resolvedfeatures-extrude.srl:393'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:393
                ('put', 'f64', (('$', 'f.cache_text'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:394'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:394
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:395'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:395
                ('put', 'f64', (-1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:396'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:396
                ('rep', 56, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:397'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:397
                ('put', 'f64', (('=', '-$f.depth'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:398'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:398
                ('rep', 16, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:399'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:399
                ('put', 'f64', (('=', '-$f.depth'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:400'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:400
                ('rep', 42, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:401'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:401
                ('put', 'u32', (131077, 131075, 0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:402'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:402
                ('put', 'f64', (-1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:403'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:403
                ('rep', 36, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:404'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:404
                ('put', 'u32', (131074,), '15.5.8 config-0-resolvedfeatures-extrude.srl:405'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:405
                ('hex', '27', '15.5.8 config-0-resolvedfeatures-extrude.srl:406'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:406
                ('put', 'u32', (8388612,), '15.5.8 config-0-resolvedfeatures-extrude.srl:407'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:407
                ('rep', 7, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:408'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:408
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:409'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:409
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:410'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:410
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:411'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:411
                ('put', 'f64', (('$', 'f.depth'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:412'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:412
                ('put', 'u32', (8, 16, 1, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:413'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:413
                ('put', 'f64', (('$', 'f.depth'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:414'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:414
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:415'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:415
                ('class', 'moFavoriteHandle_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:416'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:416
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:417'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:417
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:418'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:418
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:419'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:419
                ('put', 'f64', (-1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:420'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:420
                ('put', 'u32', (65537,), '15.5.8 config-0-resolvedfeatures-extrude.srl:421'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:421
                ('hex', 'FD', '15.5.8 config-0-resolvedfeatures-extrude.srl:422'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:422
                ('put', 'u32', (14737985,), '15.5.8 config-0-resolvedfeatures-extrude.srl:423'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:423
                ('rep', 41, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:424'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:424
                ('put', 'u32', (114745, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:425'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:425
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:426'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:426
                ('rep', 24, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:427'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:427
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:428'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:428
                ('rep', 24, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:429'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:429
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:430'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:430
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:431'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:431
                ('rep', 28, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:432'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:432
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:433'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:433
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:434'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:434
                ('put', 'f64', (1.0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:435'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:435
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:436'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:436
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:437'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:437
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:438'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:438
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:439'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:439
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:440'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:440
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:441'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:441
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:442'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:442
                ('rep', 6, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:443'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:443
                ('put', 'u32', (1002101,), '15.5.8 config-0-resolvedfeatures-extrude.srl:444'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:444
                ('rep', 18, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:445'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:445
                ('put', 'u32', (1, 1, 0, 0, 1), '15.5.8 config-0-resolvedfeatures-extrude.srl:446'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:446
                ('rep', 32, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:447'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:447
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:448'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:448
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:449'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:449
                ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:450'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:450
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:451'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:451
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:452'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:452
                ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:453'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:453
                ('put', 'u32', (('$', 'f.counter_favorite'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:454'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:454
                ('rep', 32, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:455'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:455
                ('put', 'cstr', ('',), '15.5.8 config-0-resolvedfeatures-extrude.srl:456'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:456
                ('rep', 56, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:457'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:457
                ('hex', '01', '15.5.8 config-0-resolvedfeatures-extrude.srl:458'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:458
                ('rep', 2, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:459'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:459
                ('put', 'u32', (1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:460'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:460
                ('rep', 55, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:461'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:461
                ('put', 'u32', (('=', 'int($f.merge)'),), '15.5.8 config-0-resolvedfeatures-extrude.srl:462'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:462
                ('put', 'u32', (0, 0), '15.5.8 config-0-resolvedfeatures-extrude.srl:463'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:463
                ('if', ('$', 'f.first'), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:464
                    ('class', 'moFromEndSpec_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:465'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:465
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:466'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:466
                    ('hex', '52', '15.5.8 config-0-resolvedfeatures-extrude.srl:467'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:467
                    ('put', 'u32', (9808418,), '15.5.8 config-0-resolvedfeatures-extrude.srl:468'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:468
                    ('put', 'u8', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:469'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:469
                    ('put', 'f32', (137,), '15.5.8 config-0-resolvedfeatures-extrude.srl:470'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:470
                    ('hex', 'FE4280', '15.5.8 config-0-resolvedfeatures-extrude.srl:471'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:471
                    ('put', 'u32', (207138,), '15.5.8 config-0-resolvedfeatures-extrude.srl:472'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:472
                    ('rep', 11, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:473'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:473
                    ('put', 'i32', (-1,), '15.5.8 config-0-resolvedfeatures-extrude.srl:474'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:474
                ), (  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:464
                    ('class', 'moFromEndSpec_c', 1, None, '15.5.8 config-0-resolvedfeatures-extrude.srl:476'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:476
                    ('put', 'u32', (0,), '15.5.8 config-0-resolvedfeatures-extrude.srl:477'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:477
                    ('hex', '401F6D48B1A833234C31969570FA', '15.5.8 config-0-resolvedfeatures-extrude.srl:478'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:478
                    ('put', 'u32', (94813,), '15.5.8 config-0-resolvedfeatures-extrude.srl:479'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:479
                    ('rep', 14, 0, '15.5.8 config-0-resolvedfeatures-extrude.srl:480'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:480
                ), '15.5.8 config-0-resolvedfeatures-extrude.srl:464'),  # spec 15.5.8 config-0-resolvedfeatures-extrude.srl:464
            ), '15.5.6 config-0-resolvedfeatures.srl:13'),  # spec 15.5.6 config-0-resolvedfeatures.srl:13
        ), '15.5.6 config-0-resolvedfeatures.srl:12'),  # spec 15.5.6 config-0-resolvedfeatures.srl:12
        ('put', 'u32', (0,), '15.5.1 config-0-resolvedfeatures.srl:20'),  # spec 15.5.1 config-0-resolvedfeatures.srl:20
    ),  # spec 15.5 config-0-resolvedfeatures.srl
    'Contents/CusProps': (  # spec 15.2 cusprops.srl
        ('archive', 'start', 1, '15.2.4 cusprops.srl:6'),  # spec 15.2.4 cusprops.srl:6
        ('class', 'moCusPropMgr_c', 1, None, '15.2.4 cusprops.srl:7'),  # spec 15.2.4 cusprops.srl:7
        ('put', 'i32', (('=', 'len($props)-1'),), '15.2.4 cusprops.srl:8'),  # spec 15.2.4 cusprops.srl:8
        ('put', 'u32', (1,), '15.2.4 cusprops.srl:9'),  # spec 15.2.4 cusprops.srl:9
        ('put', 'u32', (1,), '15.2.4 cusprops.srl:10'),  # spec 15.2.4 cusprops.srl:10
        ('put', 'u32', (0,), '15.2.4 cusprops.srl:12'),  # spec 15.2.4 cusprops.srl:12
        ('class', 'moCusPropContainer_c', 1, None, '15.2.4 cusprops.srl:13'),  # spec 15.2.4 cusprops.srl:13
        ('class', 'moFilePropContainer_c', 1, None, '15.2.4 cusprops.srl:14'),  # spec 15.2.4 cusprops.srl:14
        ('if', ('=', 'len($props)>0'), (  # spec 15.2.4 cusprops.srl:15
            ('class', 'suObList', 1, None, '15.2.4 cusprops.srl:16'),  # spec 15.2.4 cusprops.srl:16
            ('put', 'u16', (1,), '15.2.4 cusprops.srl:17'),  # spec 15.2.4 cusprops.srl:17
            ('class', 'moAdvCusPropList_c', 1, None, '15.2.4 cusprops.srl:18'),  # spec 15.2.4 cusprops.srl:18
            ('put', 'u16', (('=', 'len($props)'),), '15.2.4 cusprops.srl:19'),  # spec 15.2.4 cusprops.srl:19
            ('for', 'p', ('$', 'props'), False, (  # spec 15.2.4 cusprops.srl:20
                ('class', 'moAdvCusProp_c', 1, None, '15.2.4 cusprops.srl:21'),  # spec 15.2.4 cusprops.srl:21
                ('put', 'u16', (1,), '15.2.4 cusprops.srl:22'),  # spec 15.2.4 cusprops.srl:22
                ('class', 'moCusPropStringElem_c', 1, None, '15.2.4 cusprops.srl:23'),  # spec 15.2.4 cusprops.srl:23
                ('put', 'cstr', (('$', 'p.text'),), '15.2.4 cusprops.srl:24'),  # spec 15.2.4 cusprops.srl:24
                ('put', 'u32', (('$', 'p_index'),), '15.2.4 cusprops.srl:25'),  # spec 15.2.4 cusprops.srl:25
                ('put', 'u32', (9,), '15.2.4 cusprops.srl:26'),  # spec 15.2.4 cusprops.srl:26
                ('put', 'cstr', (('$', 'p.name'),), '15.2.4 cusprops.srl:27'),  # spec 15.2.4 cusprops.srl:27
                ('put', 'u32', (('$', 'p.code'),), '15.2.4 cusprops.srl:28'),  # spec 15.2.4 cusprops.srl:28
                ('put', 'cstr', (('$', 'p.text'),), '15.2.4 cusprops.srl:29'),  # spec 15.2.4 cusprops.srl:29
                ('put', 'cstr', (('$', 'p.text'),), '15.2.4 cusprops.srl:30'),  # spec 15.2.4 cusprops.srl:30
                ('put', 'i32', (-1,), '15.2.4 cusprops.srl:31'),  # spec 15.2.4 cusprops.srl:31
                ('put', 'u32', (1,), '15.2.4 cusprops.srl:32'),  # spec 15.2.4 cusprops.srl:32
                ('put', 'u32', (0,), '15.2.4 cusprops.srl:33'),  # spec 15.2.4 cusprops.srl:33
            ), '15.2.4 cusprops.srl:20'),  # spec 15.2.4 cusprops.srl:20
        ), (  # spec 15.2.4 cusprops.srl:15
            ('put', 'u16', (0,), '15.2.4 cusprops.srl:36'),  # spec 15.2.4 cusprops.srl:36
        ), '15.2.4 cusprops.srl:15'),  # spec 15.2.4 cusprops.srl:15
        ('put', 'u16', (0,), '15.2.4 cusprops.srl:38'),  # spec 15.2.4 cusprops.srl:38
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.4 cusprops.srl:39
            ('class', 'moCutListPropContainer_c', 1, None, '15.2.4 cusprops.srl:40'),  # spec 15.2.4 cusprops.srl:40
            ('rep', 8, 0, '15.2.4 cusprops.srl:41'),  # spec 15.2.4 cusprops.srl:41
        ), (  # spec 15.2.4 cusprops.srl:39
            ('put', 'u16', (0,), '15.2.4 cusprops.srl:43'),  # spec 15.2.4 cusprops.srl:43
        ), '15.2.4 cusprops.srl:39'),  # spec 15.2.4 cusprops.srl:39
        ('rep', 6, 0, '15.2.4 cusprops.srl:45'),  # spec 15.2.4 cusprops.srl:45
    ),  # spec 15.2 cusprops.srl
    'Contents/Definition': (  # spec 15.2 definition.srl
        ('put', 'u32', (7, 0, 50, 1, 1), '15.2.11.1 definition.srl:6'),  # spec 15.2.11.1 definition.srl:6
        ('put', 'u32', (2208513328,), '15.2.11.1 definition.srl:8'),  # spec 15.2.11.1 definition.srl:8
        ('put', 'u16', (10181, 4558), '15.2.11.1 definition.srl:9'),  # spec 15.2.11.1 definition.srl:9
        ('put', 'u8', (191, 212, 0, 64, 5, 19, 187, 87), '15.2.11.1 definition.srl:10'),  # spec 15.2.11.1 definition.srl:10
        ('rep', 3, 0, '15.2.11.1 definition.srl:11'),  # spec 15.2.11.1 definition.srl:11
        ('put', 'u8', (1,), '15.2.11.1 definition.srl:12'),  # spec 15.2.11.1 definition.srl:12
        ('put', 'f64', (('$', 'def.view.r.0'), ('$', 'def.view.r.1'), ('$', 'def.view.r.2')), '15.2.11.2 definition.srl:18'),  # spec 15.2.11.2 definition.srl:18
        ('put', 'f64', (('$', 'def.view.r.3'), ('$', 'def.view.r.4'), ('$', 'def.view.r.5')), '15.2.11.2 definition.srl:19'),  # spec 15.2.11.2 definition.srl:19
        ('put', 'f64', (('$', 'def.view.r.6'), ('$', 'def.view.r.7'), ('$', 'def.view.r.8')), '15.2.11.2 definition.srl:20'),  # spec 15.2.11.2 definition.srl:20
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.11.2 definition.srl:21'),  # spec 15.2.11.2 definition.srl:21
        ('put', 'f64', (1.0,), '15.2.11.2 definition.srl:22'),  # spec 15.2.11.2 definition.srl:22
        ('put', 'u16', (0,), '15.2.11.2 definition.srl:23'),  # spec 15.2.11.2 definition.srl:23
        ('put', 'f64', (('$', 'def.view.c.0'), ('$', 'def.view.c.1'), ('$', 'def.view.c.2')), '15.2.11.2 definition.srl:24'),  # spec 15.2.11.2 definition.srl:24
        ('put', 'f64', (('$', 'def.view.zoom'),), '15.2.11.2 definition.srl:25'),  # spec 15.2.11.2 definition.srl:25
        ('put', 'u8', (0,), '15.2.11.2 definition.srl:26'),  # spec 15.2.11.2 definition.srl:26
        ('put', 'u16', (3, 1), '15.2.11.2 definition.srl:27'),  # spec 15.2.11.2 definition.srl:27
        ('hex', '02FA8CA63F09140078', '15.2.11.2 definition.srl:30'),  # spec 15.2.11.2 definition.srl:30
        ('archive', 'start', 1, '15.2.11.3 definition.srl:33'),  # spec 15.2.11.3 definition.srl:33
        ('class', 'moISO_c', 1, None, '15.2.11.3 definition.srl:34'),  # spec 15.2.11.3 definition.srl:34
        ('put', 'u32', (7,), '15.2.11.3 definition.srl:35'),  # spec 15.2.11.3 definition.srl:35
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:36'),  # spec 15.2.11.3 definition.srl:36
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:37'),  # spec 15.2.11.3 definition.srl:37
        ('put', 'cstr', ('Solid',), '15.2.11.3 definition.srl:38'),  # spec 15.2.11.3 definition.srl:38
        ('put', 'u16', (1,), '15.2.11.3 definition.srl:39'),  # spec 15.2.11.3 definition.srl:39
        ('put', 'f64', (12.0,), '15.2.11.3 definition.srl:40'),  # spec 15.2.11.3 definition.srl:40
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:41'),  # spec 15.2.11.3 definition.srl:41
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:42'),  # spec 15.2.11.3 definition.srl:42
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:43'),  # spec 15.2.11.3 definition.srl:43
        ('put', 'cstr', ('Dashed',), '15.2.11.3 definition.srl:44'),  # spec 15.2.11.3 definition.srl:44
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:45'),  # spec 15.2.11.3 definition.srl:45
        ('put', 'f64', (0.25, -0.125), '15.2.11.3 definition.srl:46'),  # spec 15.2.11.3 definition.srl:46
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:47'),  # spec 15.2.11.3 definition.srl:47
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:48'),  # spec 15.2.11.3 definition.srl:48
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:49'),  # spec 15.2.11.3 definition.srl:49
        ('put', 'cstr', ('Phantom',), '15.2.11.3 definition.srl:50'),  # spec 15.2.11.3 definition.srl:50
        ('put', 'u16', (6,), '15.2.11.3 definition.srl:51'),  # spec 15.2.11.3 definition.srl:51
        ('put', 'f64', (1.25, -0.25, 0.25, -0.25, 0.25, -0.25), '15.2.11.3 definition.srl:52'),  # spec 15.2.11.3 definition.srl:52
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:53'),  # spec 15.2.11.3 definition.srl:53
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:54'),  # spec 15.2.11.3 definition.srl:54
        ('put', 'cstr', ('CHAIN',), '15.2.11.3 definition.srl:55'),  # spec 15.2.11.3 definition.srl:55
        ('put', 'cstr', ('Chain',), '15.2.11.3 definition.srl:56'),  # spec 15.2.11.3 definition.srl:56
        ('put', 'u16', (4,), '15.2.11.3 definition.srl:57'),  # spec 15.2.11.3 definition.srl:57
        ('put', 'f64', (1.25, -0.25, 0.25, -0.25), '15.2.11.3 definition.srl:58'),  # spec 15.2.11.3 definition.srl:58
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:59'),  # spec 15.2.11.3 definition.srl:59
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:60'),  # spec 15.2.11.3 definition.srl:60
        ('put', 'cstr', ('CENTER',), '15.2.11.3 definition.srl:61'),  # spec 15.2.11.3 definition.srl:61
        ('put', 'cstr', ('Center',), '15.2.11.3 definition.srl:62'),  # spec 15.2.11.3 definition.srl:62
        ('put', 'u16', (4,), '15.2.11.3 definition.srl:63'),  # spec 15.2.11.3 definition.srl:63
        ('put', 'f64', (3.0, -0.25, 0.25, -0.25), '15.2.11.3 definition.srl:64'),  # spec 15.2.11.3 definition.srl:64
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:65'),  # spec 15.2.11.3 definition.srl:65
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:66'),  # spec 15.2.11.3 definition.srl:66
        ('put', 'cstr', ('STITCH',), '15.2.11.3 definition.srl:67'),  # spec 15.2.11.3 definition.srl:67
        ('put', 'cstr', ('Stitch',), '15.2.11.3 definition.srl:68'),  # spec 15.2.11.3 definition.srl:68
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:69'),  # spec 15.2.11.3 definition.srl:69
        ('put', 'f64', (0.0, -0.125), '15.2.11.3 definition.srl:70'),  # spec 15.2.11.3 definition.srl:70
        ('put', 'u8', (0,), '15.2.11.3 definition.srl:71'),  # spec 15.2.11.3 definition.srl:71
        ('class', 'moLineStyle_c', 1, None, '15.2.11.3 definition.srl:72'),  # spec 15.2.11.3 definition.srl:72
        ('put', 'cstr', ('CHAIN_THICK',), '15.2.11.3 definition.srl:73'),  # spec 15.2.11.3 definition.srl:73
        ('put', 'cstr', ('Thin/Thick Chain',), '15.2.11.3 definition.srl:74'),  # spec 15.2.11.3 definition.srl:74
        ('put', 'u16', (4,), '15.2.11.3 definition.srl:75'),  # spec 15.2.11.3 definition.srl:75
        ('put', 'f64', (1.25, -0.25, 0.25, -0.25), '15.2.11.3 definition.srl:76'),  # spec 15.2.11.3 definition.srl:76
        ('put', 'u8', (1,), '15.2.11.3 definition.srl:77'),  # spec 15.2.11.3 definition.srl:77
        ('class', 'uiLineFontMgr_c', 1, None, '15.2.11.3 definition.srl:78'),  # spec 15.2.11.3 definition.srl:78
        ('put', 'u16', (40,), '15.2.11.3 definition.srl:79'),  # spec 15.2.11.3 definition.srl:79
        ('put', 'cstr', ('Sketch',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Auxilliary',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('ChamferDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('LinearDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('LinearDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('ArcLenDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Hidden',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('CosmeticThread',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('DUMMYTHREAD',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Explodelines',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Callout',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('BendDown',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('AngOrdinateDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Visible',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (1,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Detail',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Section',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Dimensions',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('BreakLines',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('OrdinateDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('ChamferDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Crosshatch',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('ViewArrow',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('EmphasizedOutline',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (2,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('AngleDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Adjoining Component',), '15.2.11.3 definition.srl:112'),  # spec 15.2.11.3 definition.srl:112
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:113'),  # spec 15.2.11.3 definition.srl:113
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:114'),  # spec 15.2.11.3 definition.srl:114
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:115'),  # spec 15.2.11.3 definition.srl:115
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:116'),  # spec 15.2.11.3 definition.srl:116
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:117'),  # spec 15.2.11.3 definition.srl:117
        ('put', 'cstr', ('TanHidden',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('HIDDEN',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('ArcLenDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('AngleDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('DiameterDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('EnvelopComponent',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('DiameterDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('OrdinateDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('CalloutExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('AngOrdinateDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('TanVisible',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('PHANTOM',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('RadialDim',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('Centerlines',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CENTER',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('DetailBorder',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('RadialDimExt',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('SpeedpakVisible',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'cstr', ('BendUp',), '15.2.11.3 definition.srl:82'),  # spec 15.2.11.3 definition.srl:82
        ('class', 'uiLFConfig_c', 1, None, '15.2.11.3 definition.srl:83'),  # spec 15.2.11.3 definition.srl:83
        ('put', 'cstr', ('CONTINUOUS',), '15.2.11.3 definition.srl:84'),  # spec 15.2.11.3 definition.srl:84
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:85'),  # spec 15.2.11.3 definition.srl:85
        ('put', 'f32', (-1.0,), '15.2.11.3 definition.srl:86'),  # spec 15.2.11.3 definition.srl:86
        ('put', 'u16', (0,), '15.2.11.3 definition.srl:87'),  # spec 15.2.11.3 definition.srl:87
        ('put', 'u16', (1,), '15.2.11.4 definition.srl:136'),  # spec 15.2.11.4 definition.srl:136
        ('class', 'uiUserModelEnv_c', 1, None, '15.2.11.4 definition.srl:137'),  # spec 15.2.11.4 definition.srl:137
        ('put', 'cstr', (('$', 'doc.author'),), '15.2.11.4 definition.srl:138'),  # spec 15.2.11.4 definition.srl:138
        ('put', 'u16', (1, 1), '15.2.11.4 definition.srl:139'),  # spec 15.2.11.4 definition.srl:139
        ('put', 'u16', (1230, 10, 3392, 10), '15.2.11.4 definition.srl:140'),  # spec 15.2.11.4 definition.srl:140
        ('put', 'u32', (0,), '15.2.11.4 definition.srl:141'),  # spec 15.2.11.4 definition.srl:141
        ('put', 'u8', (1,), '15.2.11.4 definition.srl:142'),  # spec 15.2.11.4 definition.srl:142
        ('put', 'f64', (('$', 'def.view.r.0'), ('$', 'def.view.r.1'), ('$', 'def.view.r.2')), '15.2.11.2 definition.srl:18'),  # spec 15.2.11.2 definition.srl:18
        ('put', 'f64', (('$', 'def.view.r.3'), ('$', 'def.view.r.4'), ('$', 'def.view.r.5')), '15.2.11.2 definition.srl:19'),  # spec 15.2.11.2 definition.srl:19
        ('put', 'f64', (('$', 'def.view.r.6'), ('$', 'def.view.r.7'), ('$', 'def.view.r.8')), '15.2.11.2 definition.srl:20'),  # spec 15.2.11.2 definition.srl:20
        ('put', 'f64', (0.0, 0.0, 0.0), '15.2.11.2 definition.srl:21'),  # spec 15.2.11.2 definition.srl:21
        ('put', 'f64', (1.0,), '15.2.11.2 definition.srl:22'),  # spec 15.2.11.2 definition.srl:22
        ('put', 'u16', (0,), '15.2.11.2 definition.srl:23'),  # spec 15.2.11.2 definition.srl:23
        ('put', 'f64', (('$', 'def.view.c.0'), ('$', 'def.view.c.1'), ('$', 'def.view.c.2')), '15.2.11.2 definition.srl:24'),  # spec 15.2.11.2 definition.srl:24
        ('put', 'f64', (('$', 'def.view.zoom'),), '15.2.11.2 definition.srl:25'),  # spec 15.2.11.2 definition.srl:25
        ('put', 'u8', (0,), '15.2.11.2 definition.srl:26'),  # spec 15.2.11.2 definition.srl:26
        ('put', 'u16', (3, 1), '15.2.11.2 definition.srl:27'),  # spec 15.2.11.2 definition.srl:27
        ('put', 'f64', (-1.0,), '15.2.11.4 definition.srl:144'),  # spec 15.2.11.4 definition.srl:144
        ('put', 'cstr', ('',), '15.2.11.4 definition.srl:145'),  # spec 15.2.11.4 definition.srl:145
        ('put', 'u32', (3391, 227), '15.2.11.4 definition.srl:146'),  # spec 15.2.11.4 definition.srl:146
        ('put', 'u16', (2,), '15.2.11.4 definition.srl:147'),  # spec 15.2.11.4 definition.srl:147
        ('put', 'u32', (1,), '15.2.11.4 definition.srl:148'),  # spec 15.2.11.4 definition.srl:148
        ('put', 'u16', (1180, 227, 10), '15.2.11.4 definition.srl:149'),  # spec 15.2.11.4 definition.srl:149
        ('put', 'i32', (-1,), '15.2.11.4 definition.srl:150'),  # spec 15.2.11.4 definition.srl:150
        ('rep', 25, 0, '15.2.11.4 definition.srl:153'),  # spec 15.2.11.4 definition.srl:153
        ('put', 'f64', (1.0,), '15.2.11.4 definition.srl:154'),  # spec 15.2.11.4 definition.srl:154
        ('rep', 26, 0, '15.2.11.4 definition.srl:155'),  # spec 15.2.11.4 definition.srl:155
        ('put', 'f64', (1.0,), '15.2.11.4 definition.srl:156'),  # spec 15.2.11.4 definition.srl:156
        ('put', 'u8', (0,), '15.2.11.4 definition.srl:157'),  # spec 15.2.11.4 definition.srl:157
        ('put', 'u32', (65535,), '15.2.11.4 definition.srl:158'),  # spec 15.2.11.4 definition.srl:158
        ('put', 'f64', (-1.0,), '15.2.11.4 definition.srl:159'),  # spec 15.2.11.4 definition.srl:159
        ('put', 'cstr', ('',), '15.2.11.4 definition.srl:160'),  # spec 15.2.11.4 definition.srl:160
        ('rep', 25, 0, '15.2.11.4 definition.srl:153'),  # spec 15.2.11.4 definition.srl:153
        ('put', 'f64', (1.0,), '15.2.11.4 definition.srl:154'),  # spec 15.2.11.4 definition.srl:154
        ('rep', 26, 0, '15.2.11.4 definition.srl:155'),  # spec 15.2.11.4 definition.srl:155
        ('put', 'f64', (1.0,), '15.2.11.4 definition.srl:156'),  # spec 15.2.11.4 definition.srl:156
        ('put', 'u8', (0,), '15.2.11.4 definition.srl:157'),  # spec 15.2.11.4 definition.srl:157
        ('put', 'u32', (65535,), '15.2.11.4 definition.srl:158'),  # spec 15.2.11.4 definition.srl:158
        ('put', 'f64', (-1.0,), '15.2.11.4 definition.srl:159'),  # spec 15.2.11.4 definition.srl:159
        ('put', 'cstr', ('',), '15.2.11.4 definition.srl:160'),  # spec 15.2.11.4 definition.srl:160
        ('rep', 12, 0, '15.2.11.4 definition.srl:164'),  # spec 15.2.11.4 definition.srl:164
        ('put', 'u32', (96,), '15.2.11.4 definition.srl:165'),  # spec 15.2.11.4 definition.srl:165
        ('rep', 20, 0, '15.2.11.4 definition.srl:166'),  # spec 15.2.11.4 definition.srl:166
        ('put', 'i32', (-1, -1), '15.2.11.4 definition.srl:167'),  # spec 15.2.11.4 definition.srl:167
        ('hex', '3520010000', '15.2.11.4 definition.srl:168'),  # spec 15.2.11.4 definition.srl:168
        ('class', 'moBomInfoMgr_c', 1, None, '15.2.11.5 definition.srl:171'),  # spec 15.2.11.5 definition.srl:171
        ('put', 'u32', (0,), '15.2.11.5 definition.srl:172'),  # spec 15.2.11.5 definition.srl:172
        ('put', 'u16', (1,), '15.2.11.5 definition.srl:173'),  # spec 15.2.11.5 definition.srl:173
        ('put', 'u32', (38284, 0, 515), '15.2.11.5 definition.srl:174'),  # spec 15.2.11.5 definition.srl:174
        ('class', 'uoJournal_c', 0, None, '15.2.11.5 definition.srl:175'),  # spec 15.2.11.5 definition.srl:175
        ('put', 'cstr', ('Design Journal.doc',), '15.2.11.5 definition.srl:176'),  # spec 15.2.11.5 definition.srl:176
        ('rep', 10, 0, '15.2.11.5 definition.srl:177'),  # spec 15.2.11.5 definition.srl:177
        ('put', 'u32', (1,), '15.2.11.5 definition.srl:178'),  # spec 15.2.11.5 definition.srl:178
        ('put', 'u16', (0,), '15.2.11.5 definition.srl:179'),  # spec 15.2.11.5 definition.srl:179
        ('put', 'u32', (1,), '15.2.11.5 definition.srl:180'),  # spec 15.2.11.5 definition.srl:180
        ('rep', 9, 0, '15.2.11.5 definition.srl:181'),  # spec 15.2.11.5 definition.srl:181
        ('put', 'u32', (1,), '15.2.11.5 definition.srl:182'),  # spec 15.2.11.5 definition.srl:182
        ('rep', 3, 0, '15.2.11.5 definition.srl:183'),  # spec 15.2.11.5 definition.srl:183
        ('put', 'u32', (1025,), '15.2.11.5 definition.srl:184'),  # spec 15.2.11.5 definition.srl:184
        ('rep', 7, 0, '15.2.11.5 definition.srl:185'),  # spec 15.2.11.5 definition.srl:185
        ('put', 'cstr', ('',), '15.2.11.5 definition.srl:186'),  # spec 15.2.11.5 definition.srl:186
        ('put', 'u16', (0,), '15.2.11.5 definition.srl:187'),  # spec 15.2.11.5 definition.srl:187
        ('put', 'cstr', ('',), '15.2.11.5 definition.srl:188'),  # spec 15.2.11.5 definition.srl:188
        ('put', 'u16', (0,), '15.2.11.5 definition.srl:189'),  # spec 15.2.11.5 definition.srl:189
        ('put', 'cstr', ('',), '15.2.11.5 definition.srl:190'),  # spec 15.2.11.5 definition.srl:190
        ('rep', 32, 0, '15.2.11.5 definition.srl:191'),  # spec 15.2.11.5 definition.srl:191
        ('put', 'u32', (100, 5), '15.2.11.5 definition.srl:192'),  # spec 15.2.11.5 definition.srl:192
        ('rep', 8, 0, '15.2.11.5 definition.srl:193'),  # spec 15.2.11.5 definition.srl:193
        ('put', 'u32', (1,), '15.2.11.5 definition.srl:194'),  # spec 15.2.11.5 definition.srl:194
        ('rep', 12, 0, '15.2.11.5 definition.srl:195'),  # spec 15.2.11.5 definition.srl:195
        ('put', 'u32', (1,), '15.2.11.5 definition.srl:196'),  # spec 15.2.11.5 definition.srl:196
        ('rep', 8, 0, '15.2.11.5 definition.srl:197'),  # spec 15.2.11.5 definition.srl:197
        ('put', 'u32', (1, 1, 0, 1), '15.2.11.5 definition.srl:198'),  # spec 15.2.11.5 definition.srl:198
        ('rep', 6, 0, '15.2.11.5 definition.srl:199'),  # spec 15.2.11.5 definition.srl:199
        ('put', 'u32', (1, 1), '15.2.11.5 definition.srl:200'),  # spec 15.2.11.5 definition.srl:200
        ('rep', 12, 0, '15.2.11.5 definition.srl:201'),  # spec 15.2.11.5 definition.srl:201
        ('put', 'u32', (2,), '15.2.11.5 definition.srl:202'),  # spec 15.2.11.5 definition.srl:202
        ('rep', 14, 0, '15.2.11.5 definition.srl:203'),  # spec 15.2.11.5 definition.srl:203
        ('put', 'u32', (3, 1, 0), '15.2.11.5 definition.srl:204'),  # spec 15.2.11.5 definition.srl:204
        ('put', 'f64', (1000.0,), '15.2.11.5 definition.srl:205'),  # spec 15.2.11.5 definition.srl:205
    ),  # spec 15.2 definition.srl
    'Contents/OleItems': (  # spec 15.1 oleitems.srl
        ('put', 'u32', (0,), '15.1.7 oleitems.srl:4'),  # spec 15.1.7 oleitems.srl:4
    ),  # spec 15.1 oleitems.srl
    'Contents/eModelLic': (  # spec 15.1 emodellic.srl
        ('put', 'u32', (2,), '15.1.7 emodellic.srl:4'),  # spec 15.1.7 emodellic.srl:4
    ),  # spec 15.1 emodellic.srl
    'Header2': (  # spec 15.2 header2.srl
        ('archive', 'start', 1, '15.2.2 model-header.srl:4'),  # spec 15.2.2 model-header.srl:4
        ('class', 'moHeader_c', 1, None, '15.2.2.1 model-header.srl:6'),  # spec 15.2.2.1 model-header.srl:6
        ('put', 'u32', (1,), '15.2.2.1 model-header.srl:7'),  # spec 15.2.2.1 model-header.srl:7
        ('class', 'su_CStringArray', 0, None, '15.2.2.1 model-header.srl:8'),  # spec 15.2.2.1 model-header.srl:8
        ('put', 'u16', (1,), '15.2.2.1 model-header.srl:9'),  # spec 15.2.2.1 model-header.srl:9
        ('put', 'cstr', (('$', 'doc.author'),), '15.2.2.1 model-header.srl:10'),  # spec 15.2.2.1 model-header.srl:10
        ('class', 'su_CStringArray', 0, None, '15.2.2.1 model-header.srl:11'),  # spec 15.2.2.1 model-header.srl:11
        ('put', 'u16', (1,), '15.2.2.1 model-header.srl:12'),  # spec 15.2.2.1 model-header.srl:12
        ('put', 'cstr', ('',), '15.2.2.1 model-header.srl:13'),  # spec 15.2.2.1 model-header.srl:13
        ('class', 'suObList', 1, None, '15.2.2.2 model-header.srl:32'),  # spec 15.2.2.2 model-header.srl:32
        ('put', 'u16', (('=', '24+len($features)'),), '15.2.2.2 model-header.srl:33'),  # spec 15.2.2.2 model-header.srl:33
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:35'),  # spec 15.2.2.2 model-header.srl:35
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:36'),  # spec 15.2.2.2 model-header.srl:36
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:38'),  # spec 15.2.2.2 model-header.srl:38
        ('put', 'cstr', ('Part1^Assem1',), '15.2.2.2 model-header.srl:39'),  # spec 15.2.2.2 model-header.srl:39
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:40'),  # spec 15.2.2.2 model-header.srl:40
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:41'),  # spec 15.2.2.2 model-header.srl:41
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (1,), '15.2.2.2 model-header.srl:43'),  # spec 15.2.2.2 model-header.srl:43
        ('put', 'cstr', ('Annotations',), '15.2.2.2 model-header.srl:44'),  # spec 15.2.2.2 model-header.srl:44
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:45'),  # spec 15.2.2.2 model-header.srl:45
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:46'),  # spec 15.2.2.2 model-header.srl:46
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (2,), '15.2.2.2 model-header.srl:49'),  # spec 15.2.2.2 model-header.srl:49
        ('put', 'cstr', ('Front Plane',), '15.2.2.2 model-header.srl:50'),  # spec 15.2.2.2 model-header.srl:50
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:51'),  # spec 15.2.2.2 model-header.srl:51
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:52'),  # spec 15.2.2.2 model-header.srl:52
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (3,), '15.2.2.2 model-header.srl:55'),  # spec 15.2.2.2 model-header.srl:55
        ('put', 'cstr', ('Top Plane',), '15.2.2.2 model-header.srl:56'),  # spec 15.2.2.2 model-header.srl:56
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:57'),  # spec 15.2.2.2 model-header.srl:57
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:58'),  # spec 15.2.2.2 model-header.srl:58
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (4,), '15.2.2.2 model-header.srl:61'),  # spec 15.2.2.2 model-header.srl:61
        ('put', 'cstr', ('Right Plane',), '15.2.2.2 model-header.srl:62'),  # spec 15.2.2.2 model-header.srl:62
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:63'),  # spec 15.2.2.2 model-header.srl:63
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:64'),  # spec 15.2.2.2 model-header.srl:64
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (5,), '15.2.2.2 model-header.srl:67'),  # spec 15.2.2.2 model-header.srl:67
        ('put', 'cstr', ('Origin',), '15.2.2.2 model-header.srl:68'),  # spec 15.2.2.2 model-header.srl:68
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:69'),  # spec 15.2.2.2 model-header.srl:69
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:70'),  # spec 15.2.2.2 model-header.srl:70
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (6,), '15.2.2.2 model-header.srl:72'),  # spec 15.2.2.2 model-header.srl:72
        ('put', 'cstr', ('Lights and Cameras',), '15.2.2.2 model-header.srl:73'),  # spec 15.2.2.2 model-header.srl:73
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:74'),  # spec 15.2.2.2 model-header.srl:74
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:75'),  # spec 15.2.2.2 model-header.srl:75
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (7,), '15.2.2.2 model-header.srl:77'),  # spec 15.2.2.2 model-header.srl:77
        ('put', 'cstr', ('Design Binder',), '15.2.2.2 model-header.srl:78'),  # spec 15.2.2.2 model-header.srl:78
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:79'),  # spec 15.2.2.2 model-header.srl:79
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:80'),  # spec 15.2.2.2 model-header.srl:80
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (8,), '15.2.2.2 model-header.srl:82'),  # spec 15.2.2.2 model-header.srl:82
        ('put', 'cstr', ('Comments',), '15.2.2.2 model-header.srl:83'),  # spec 15.2.2.2 model-header.srl:83
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:84'),  # spec 15.2.2.2 model-header.srl:84
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:85'),  # spec 15.2.2.2 model-header.srl:85
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (9,), '15.2.2.2 model-header.srl:87'),  # spec 15.2.2.2 model-header.srl:87
        ('put', 'cstr', ('Solid Bodies',), '15.2.2.2 model-header.srl:88'),  # spec 15.2.2.2 model-header.srl:88
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:89'),  # spec 15.2.2.2 model-header.srl:89
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:90'),  # spec 15.2.2.2 model-header.srl:90
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (10,), '15.2.2.2 model-header.srl:92'),  # spec 15.2.2.2 model-header.srl:92
        ('put', 'cstr', ('Surface Bodies',), '15.2.2.2 model-header.srl:93'),  # spec 15.2.2.2 model-header.srl:93
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:94'),  # spec 15.2.2.2 model-header.srl:94
        ('put', 'u16', (2,), '15.2.2.2 model-header.srl:95'),  # spec 15.2.2.2 model-header.srl:95
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
        ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
        ('put', 'u32', (11,), '15.2.2.2 model-header.srl:98'),  # spec 15.2.2.2 model-header.srl:98
        ('put', 'cstr', ('Material <not specified>',), '15.2.2.2 model-header.srl:99'),  # spec 15.2.2.2 model-header.srl:99
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:100'),  # spec 15.2.2.2 model-header.srl:100
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:101'),  # spec 15.2.2.2 model-header.srl:101
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (12,), '15.2.2.2 model-header.srl:103'),  # spec 15.2.2.2 model-header.srl:103
        ('put', 'cstr', ('Ambient',), '15.2.2.2 model-header.srl:104'),  # spec 15.2.2.2 model-header.srl:104
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:105'),  # spec 15.2.2.2 model-header.srl:105
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:106'),  # spec 15.2.2.2 model-header.srl:106
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (13,), '15.2.2.2 model-header.srl:108'),  # spec 15.2.2.2 model-header.srl:108
        ('put', 'cstr', ('Directional1',), '15.2.2.2 model-header.srl:109'),  # spec 15.2.2.2 model-header.srl:109
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:110'),  # spec 15.2.2.2 model-header.srl:110
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:111'),  # spec 15.2.2.2 model-header.srl:111
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (14,), '15.2.2.2 model-header.srl:113'),  # spec 15.2.2.2 model-header.srl:113
        ('put', 'cstr', ('Directional2',), '15.2.2.2 model-header.srl:114'),  # spec 15.2.2.2 model-header.srl:114
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:115'),  # spec 15.2.2.2 model-header.srl:115
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:116'),  # spec 15.2.2.2 model-header.srl:116
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (15,), '15.2.2.2 model-header.srl:118'),  # spec 15.2.2.2 model-header.srl:118
        ('put', 'cstr', ('Directional3',), '15.2.2.2 model-header.srl:119'),  # spec 15.2.2.2 model-header.srl:119
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:120'),  # spec 15.2.2.2 model-header.srl:120
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:121'),  # spec 15.2.2.2 model-header.srl:121
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (16,), '15.2.2.2 model-header.srl:123'),  # spec 15.2.2.2 model-header.srl:123
        ('put', 'cstr', ('Equations',), '15.2.2.2 model-header.srl:124'),  # spec 15.2.2.2 model-header.srl:124
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:126'),  # spec 15.2.2.2 model-header.srl:126
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:127'),  # spec 15.2.2.2 model-header.srl:127
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (17,), '15.2.2.2 model-header.srl:129'),  # spec 15.2.2.2 model-header.srl:129
        ('put', 'cstr', ('Notes',), '15.2.2.2 model-header.srl:130'),  # spec 15.2.2.2 model-header.srl:130
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:131'),  # spec 15.2.2.2 model-header.srl:131
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:132'),  # spec 15.2.2.2 model-header.srl:132
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (18,), '15.2.2.2 model-header.srl:134'),  # spec 15.2.2.2 model-header.srl:134
        ('put', 'cstr', ('Notes1___EndTag___',), '15.2.2.2 model-header.srl:135'),  # spec 15.2.2.2 model-header.srl:135
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:136'),  # spec 15.2.2.2 model-header.srl:136
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:137'),  # spec 15.2.2.2 model-header.srl:137
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (21,), '15.2.2.2 model-header.srl:139'),  # spec 15.2.2.2 model-header.srl:139
        ('put', 'cstr', ('Markups',), '15.2.2.2 model-header.srl:140'),  # spec 15.2.2.2 model-header.srl:140
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:141'),  # spec 15.2.2.2 model-header.srl:141
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:142'),  # spec 15.2.2.2 model-header.srl:142
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (22,), '15.2.2.2 model-header.srl:144'),  # spec 15.2.2.2 model-header.srl:144
        ('put', 'cstr', ('Sensors',), '15.2.2.2 model-header.srl:145'),  # spec 15.2.2.2 model-header.srl:145
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:146'),  # spec 15.2.2.2 model-header.srl:146
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:147'),  # spec 15.2.2.2 model-header.srl:147
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (23,), '15.2.2.2 model-header.srl:149'),  # spec 15.2.2.2 model-header.srl:149
        ('put', 'cstr', ('Favorites',), '15.2.2.2 model-header.srl:150'),  # spec 15.2.2.2 model-header.srl:150
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:151'),  # spec 15.2.2.2 model-header.srl:151
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:152'),  # spec 15.2.2.2 model-header.srl:152
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (24,), '15.2.2.2 model-header.srl:154'),  # spec 15.2.2.2 model-header.srl:154
        ('put', 'cstr', ('Folder ',), '15.2.2.2 model-header.srl:155'),  # spec 15.2.2.2 model-header.srl:155
        ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:156'),  # spec 15.2.2.2 model-header.srl:156
        ('put', 'u16', (1,), '15.2.2.2 model-header.srl:157'),  # spec 15.2.2.2 model-header.srl:157
        ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
        ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
        ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
        ('put', 'u32', (25,), '15.2.2.2 model-header.srl:159'),  # spec 15.2.2.2 model-header.srl:159
        ('put', 'cstr', ('Selection Sets',), '15.2.2.2 model-header.srl:160'),  # spec 15.2.2.2 model-header.srl:160
        ('for', 'f', ('$', 'features'), False, (  # spec 15.2.2.2 model-header.srl:162
            ('class', 'moLogs_c', 1, None, '15.2.2.2 model-header.srl:163'),  # spec 15.2.2.2 model-header.srl:163
            ('if', ('$', 'f.sketch'), (  # spec 15.2.2.2 model-header.srl:164
                ('put', 'u16', (2,), '15.2.2.2 model-header.srl:165'),  # spec 15.2.2.2 model-header.srl:165
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
                ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
                ('put', 'u32', (('$', 'f.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
                ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:26'),  # spec 15.2.2.2 model-header.srl:26
                ('put', 'u16', (1,), '15.2.2.2 model-header.srl:27'),  # spec 15.2.2.2 model-header.srl:27
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:28'),  # spec 15.2.2.2 model-header.srl:28
                ('put', 'u32', (('$', 'f.modified'),), '15.2.2.2 model-header.srl:29'),  # spec 15.2.2.2 model-header.srl:29
                ('put', 'cstr', ('Modified',), '15.2.2.2 model-header.srl:30'),  # spec 15.2.2.2 model-header.srl:30
            ), (  # spec 15.2.2.2 model-header.srl:164
                ('put', 'u16', (1,), '15.2.2.2 model-header.srl:169'),  # spec 15.2.2.2 model-header.srl:169
                ('class', 'moStamp_c', 1, None, '15.2.2.2 model-header.srl:19'),  # spec 15.2.2.2 model-header.srl:19
                ('put', 'u16', (0,), '15.2.2.2 model-header.srl:20'),  # spec 15.2.2.2 model-header.srl:20
                ('put', 'u32', (0,), '15.2.2.2 model-header.srl:21'),  # spec 15.2.2.2 model-header.srl:21
                ('put', 'u32', (('$', 'f.created'),), '15.2.2.2 model-header.srl:22'),  # spec 15.2.2.2 model-header.srl:22
                ('put', 'cstr', ('Created',), '15.2.2.2 model-header.srl:23'),  # spec 15.2.2.2 model-header.srl:23
            ), '15.2.2.2 model-header.srl:164'),  # spec 15.2.2.2 model-header.srl:164
            ('put', 'u32', (('$', 'f.id'),), '15.2.2.2 model-header.srl:172'),  # spec 15.2.2.2 model-header.srl:172
            ('put', 'cstr', (('$', 'f.name'),), '15.2.2.2 model-header.srl:173'),  # spec 15.2.2.2 model-header.srl:173
        ), '15.2.2.2 model-header.srl:162'),  # spec 15.2.2.2 model-header.srl:162
        ('put', 'u32', (('$', 'tpl.unix2'),), '15.2.2.2 model-header.srl:175'),  # spec 15.2.2.2 model-header.srl:175
        ('put', 'u32', (('$', 'hdr.next_id'),), '15.2.2.2 model-header.srl:176'),  # spec 15.2.2.2 model-header.srl:176
        ('put', 'u16', (0,), '15.2.2.2 model-header.srl:177'),  # spec 15.2.2.2 model-header.srl:177
        ('put', 'u32', (('$', 'doc.stamp'),), '15.2.2.2 model-header.srl:178'),  # spec 15.2.2.2 model-header.srl:178
        ('class', 'moExtObject_c', 1, None, '15.2.2.5 model-header.srl:181'),  # spec 15.2.2.5 model-header.srl:181
        ('class', 'moCStringHandle_c', 1, None, '15.2.2.5 model-header.srl:182'),  # spec 15.2.2.5 model-header.srl:182
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:183'),  # spec 15.2.2.5 model-header.srl:183
        ('class', 'moCStringHandle_c', 1, None, '15.2.2.5 model-header.srl:184'),  # spec 15.2.2.5 model-header.srl:184
        ('put', 'cstr', (('$', 'doc.name'),), '15.2.2.5 model-header.srl:185'),  # spec 15.2.2.5 model-header.srl:185
        ('hex', '020000', '15.2.2.5 model-header.srl:186'),  # spec 15.2.2.5 model-header.srl:186
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.5 model-header.srl:187'),  # spec 15.2.2.5 model-header.srl:187
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:188'),  # spec 15.2.2.5 model-header.srl:188
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:189'),  # spec 15.2.2.5 model-header.srl:189
        ('put', 'cstr', ('',), '15.2.2.5 model-header.srl:190'),  # spec 15.2.2.5 model-header.srl:190
        ('put', 'u16', (0,), '15.2.2.5 model-header.srl:191'),  # spec 15.2.2.5 model-header.srl:191
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.2.5 model-header.srl:192
            ('put', 'u32', (('$', 'doc.unix'),), '15.2.2.5 model-header.srl:193'),  # spec 15.2.2.5 model-header.srl:193
        ), (  # spec 15.2.2.5 model-header.srl:192
            ('put', 'u32', (('$', 'tpl.unix2'),), '15.2.2.5 model-header.srl:195'),  # spec 15.2.2.5 model-header.srl:195
        ), '15.2.2.5 model-header.srl:192'),  # spec 15.2.2.5 model-header.srl:192
        ('put', 'u32', (1, 0), '15.2.2.5 model-header.srl:197'),  # spec 15.2.2.5 model-header.srl:197
        ('put', 'i32', (-1,), '15.2.2.5 model-header.srl:198'),  # spec 15.2.2.5 model-header.srl:198
        ('put', 'cstr', ('Default',), '15.2.2.5 model-header.srl:199'),  # spec 15.2.2.5 model-header.srl:199
        ('rep', 16, 0, '15.2.2.5 model-header.srl:200'),  # spec 15.2.2.5 model-header.srl:200
        ('put', 'u32', (('$', 'doc.stamp2'),), '15.2.2.5 model-header.srl:201'),  # spec 15.2.2.5 model-header.srl:201
        ('put', 'u32', (0, 0), '15.2.2.5 model-header.srl:202'),  # spec 15.2.2.5 model-header.srl:202
        ('put', 'u32', (('$', 'doc.created'),), '15.2.2.5 model-header.srl:203'),  # spec 15.2.2.5 model-header.srl:203
        ('rep', 18, 0, '15.2.2.5 model-header.srl:204'),  # spec 15.2.2.5 model-header.srl:204
        ('put', 'u32', (2,), '15.2.2.5 model-header.srl:205'),  # spec 15.2.2.5 model-header.srl:205
        ('if', ('=', 'len($features)>0'), (  # spec 15.2.2.5 model-header.srl:206
            ('put', 'u32', (('$', 'doc.unix'),), '15.2.2.5 model-header.srl:207'),  # spec 15.2.2.5 model-header.srl:207
        ), (  # spec 15.2.2.5 model-header.srl:206
            ('put', 'u32', (('$', 'tpl.unix'),), '15.2.2.5 model-header.srl:209'),  # spec 15.2.2.5 model-header.srl:209
        ), '15.2.2.5 model-header.srl:206'),  # spec 15.2.2.5 model-header.srl:206
        ('class', 'suObList', 1, None, '15.2.2.5 model-header.srl:211'),  # spec 15.2.2.5 model-header.srl:211
        ('put', 'u16', (0,), '15.2.2.5 model-header.srl:212'),  # spec 15.2.2.5 model-header.srl:212
        ('put', 'u32', (0, 0), '15.2.2.5 model-header.srl:213'),  # spec 15.2.2.5 model-header.srl:213
        ('if', ('$', 'model.solid'), (  # spec 15.2.2.6 model-header.srl:217
            ('put', 'u32', (1,), '15.2.2.6 model-header.srl:218'),  # spec 15.2.2.6 model-header.srl:218
            ('put', 'f64', (('$', 'hdr.centre.0'), ('$', 'hdr.centre.1'), ('$', 'hdr.centre.2')), '15.2.2.6 model-header.srl:219'),  # spec 15.2.2.6 model-header.srl:219
            ('put', 'f64', (('$', 'model.max.0'), ('$', 'model.max.1'), ('$', 'model.max.2')), '15.2.2.6 model-header.srl:220'),  # spec 15.2.2.6 model-header.srl:220
            ('put', 'f64', (('$', 'model.min.0'), ('$', 'model.min.1'), ('$', 'model.min.2')), '15.2.2.6 model-header.srl:221'),  # spec 15.2.2.6 model-header.srl:221
            ('put', 'f64', (('$', 'model.sphere.3'),), '15.2.2.6 model-header.srl:222'),  # spec 15.2.2.6 model-header.srl:222
        ), (  # spec 15.2.2.6 model-header.srl:217
            ('put', 'u32', (0,), '15.2.2.6 model-header.srl:224'),  # spec 15.2.2.6 model-header.srl:224
        ), '15.2.2.6 model-header.srl:217'),  # spec 15.2.2.6 model-header.srl:217
        ('put', 'i32', (-1, -1, -1), '15.2.2.6 model-header.srl:226'),  # spec 15.2.2.6 model-header.srl:226
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:227'),  # spec 15.2.2.6 model-header.srl:227
        ('rep', 40, 0, '15.2.2.6 model-header.srl:228'),  # spec 15.2.2.6 model-header.srl:228
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:229'),  # spec 15.2.2.6 model-header.srl:229
        ('rep', 16, 0, '15.2.2.6 model-header.srl:230'),  # spec 15.2.2.6 model-header.srl:230
        ('put', 'u32', (1,), '15.2.2.6 model-header.srl:231'),  # spec 15.2.2.6 model-header.srl:231
    ),  # spec 15.2 header2.srl
    'ModelStamps': (  # spec 15.1 modelstamps.srl
        ('put', 'u32', (('$', 'doc.created'),), '15.1.7 modelstamps.srl:4'),  # spec 15.1.7 modelstamps.srl:4
        ('put', 'u32', (('$', 'doc.stamp'),), '15.1.7 modelstamps.srl:5'),  # spec 15.1.7 modelstamps.srl:5
        ('put', 'u32', (('$', 'doc.stamp2'),), '15.1.7 modelstamps.srl:6'),  # spec 15.1.7 modelstamps.srl:6
    ),  # spec 15.1 modelstamps.srl
    'OleItemInformation/OLE_Item_Data': (  # spec 15.1 ole-item-data.srl
        ('put', 'u32', (0,), '15.1.7 ole-item-data.srl:4'),  # spec 15.1.7 ole-item-data.srl:4
    ),  # spec 15.1 ole-item-data.srl
    'SwDocContentMgr/SwDocContentMgrInfo': (  # spec 15.1 swdoccontentmgrinfo.srl
        ('class', 'moBCModeInfo_c', 1, None, '15.1.6 swdoccontentmgrinfo.srl:6'),  # spec 15.1.6 swdoccontentmgrinfo.srl:6
        ('put', 'cstr', ('',), '15.1.6 swdoccontentmgrinfo.srl:7'),  # spec 15.1.6 swdoccontentmgrinfo.srl:7
        ('put', 'u32', (('$', 'doc.created'),), '15.1.6 swdoccontentmgrinfo.srl:8'),  # spec 15.1.6 swdoccontentmgrinfo.srl:8
        ('put', 'cstr', ('',), '15.1.6 swdoccontentmgrinfo.srl:9'),  # spec 15.1.6 swdoccontentmgrinfo.srl:9
        ('put', 'u32', (0,), '15.1.6 swdoccontentmgrinfo.srl:10'),  # spec 15.1.6 swdoccontentmgrinfo.srl:10
        ('put', 'u16', (0,), '15.1.6 swdoccontentmgrinfo.srl:11'),  # spec 15.1.6 swdoccontentmgrinfo.srl:11
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:12'),  # spec 15.1.6 swdoccontentmgrinfo.srl:12
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:13'),  # spec 15.1.6 swdoccontentmgrinfo.srl:13
        ('put', 'cstr', ('Material <not specified>',), '15.1.6 swdoccontentmgrinfo.srl:14'),  # spec 15.1.6 swdoccontentmgrinfo.srl:14
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:15'),  # spec 15.1.6 swdoccontentmgrinfo.srl:15
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:16'),  # spec 15.1.6 swdoccontentmgrinfo.srl:16
        ('put', 'cstr', ('Steel',), '15.1.6 swdoccontentmgrinfo.srl:17'),  # spec 15.1.6 swdoccontentmgrinfo.srl:17
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:18'),  # spec 15.1.6 swdoccontentmgrinfo.srl:18
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:19'),  # spec 15.1.6 swdoccontentmgrinfo.srl:19
        ('put', 'u32', (0,), '15.1.6 swdoccontentmgrinfo.srl:20'),  # spec 15.1.6 swdoccontentmgrinfo.srl:20
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:21'),  # spec 15.1.6 swdoccontentmgrinfo.srl:21
        ('class', 'su_CStringArray', 0, None, '15.1.6 swdoccontentmgrinfo.srl:22'),  # spec 15.1.6 swdoccontentmgrinfo.srl:22
        ('put', 'u16', (0,), '15.1.6 swdoccontentmgrinfo.srl:23'),  # spec 15.1.6 swdoccontentmgrinfo.srl:23
        ('put', 'u32', (('$', 'doc.changed'),), '15.1.6 swdoccontentmgrinfo.srl:24'),  # spec 15.1.6 swdoccontentmgrinfo.srl:24
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:25'),  # spec 15.1.6 swdoccontentmgrinfo.srl:25
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:26'),  # spec 15.1.6 swdoccontentmgrinfo.srl:26
        ('put', 'cstr', ('',), '15.1.6 swdoccontentmgrinfo.srl:27'),  # spec 15.1.6 swdoccontentmgrinfo.srl:27
        ('put', 'u32', (0, 4, 1), '15.1.6 swdoccontentmgrinfo.srl:28'),  # spec 15.1.6 swdoccontentmgrinfo.srl:28
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:29'),  # spec 15.1.6 swdoccontentmgrinfo.srl:29
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:30'),  # spec 15.1.6 swdoccontentmgrinfo.srl:30
        ('put', 'u32', (('=', 'len($bodies)'),), '15.1.6 swdoccontentmgrinfo.srl:31'),  # spec 15.1.6 swdoccontentmgrinfo.srl:31
        ('if', ('=', 'len($bodies)>0'), (  # spec 15.1.6 swdoccontentmgrinfo.srl:32
            ('put', 'u32', (('=', 'len($bodies)'),), '15.1.6 swdoccontentmgrinfo.srl:33'),  # spec 15.1.6 swdoccontentmgrinfo.srl:33
            ('for', 'b', ('$', 'bodies'), False, (  # spec 15.1.6 swdoccontentmgrinfo.srl:34
                ('put', 'u32', (('$', 'b.id'),), '15.1.6 swdoccontentmgrinfo.srl:35'),  # spec 15.1.6 swdoccontentmgrinfo.srl:35
                ('put', 'cstr', (('$', 'b.name'),), '15.1.6 swdoccontentmgrinfo.srl:36'),  # spec 15.1.6 swdoccontentmgrinfo.srl:36
            ), '15.1.6 swdoccontentmgrinfo.srl:34'),  # spec 15.1.6 swdoccontentmgrinfo.srl:34
        ), (  # spec 15.1.6 swdoccontentmgrinfo.srl:32
        ), '15.1.6 swdoccontentmgrinfo.srl:32'),  # spec 15.1.6 swdoccontentmgrinfo.srl:32
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:39'),  # spec 15.1.6 swdoccontentmgrinfo.srl:39
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:40'),  # spec 15.1.6 swdoccontentmgrinfo.srl:40
        ('put', 'u32', (('=', 'len($bodies)'),), '15.1.6 swdoccontentmgrinfo.srl:41'),  # spec 15.1.6 swdoccontentmgrinfo.srl:41
        ('if', ('=', 'len($bodies)>0'), (  # spec 15.1.6 swdoccontentmgrinfo.srl:42
            ('put', 'u32', (('=', 'len($bodies)'),), '15.1.6 swdoccontentmgrinfo.srl:43'),  # spec 15.1.6 swdoccontentmgrinfo.srl:43
            ('for', 'b', ('$', 'bodies'), False, (  # spec 15.1.6 swdoccontentmgrinfo.srl:44
                ('put', 'u32', (('$', 'b.id'),), '15.1.6 swdoccontentmgrinfo.srl:45'),  # spec 15.1.6 swdoccontentmgrinfo.srl:45
                ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:46'),  # spec 15.1.6 swdoccontentmgrinfo.srl:46
            ), '15.1.6 swdoccontentmgrinfo.srl:44'),  # spec 15.1.6 swdoccontentmgrinfo.srl:44
        ), (  # spec 15.1.6 swdoccontentmgrinfo.srl:42
        ), '15.1.6 swdoccontentmgrinfo.srl:42'),  # spec 15.1.6 swdoccontentmgrinfo.srl:42
        ('put', 'u32', (('$', 'doc.stamp'),), '15.1.6 swdoccontentmgrinfo.srl:49'),  # spec 15.1.6 swdoccontentmgrinfo.srl:49
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:50'),  # spec 15.1.6 swdoccontentmgrinfo.srl:50
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:51'),  # spec 15.1.6 swdoccontentmgrinfo.srl:51
        ('put', 'u32', (2151678336,), '15.1.6 swdoccontentmgrinfo.srl:52'),  # spec 15.1.6 swdoccontentmgrinfo.srl:52
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:53'),  # spec 15.1.6 swdoccontentmgrinfo.srl:53
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:54'),  # spec 15.1.6 swdoccontentmgrinfo.srl:54
        ('put', 'f64', (-1.0,), '15.1.6 swdoccontentmgrinfo.srl:55'),  # spec 15.1.6 swdoccontentmgrinfo.srl:55
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:56'),  # spec 15.1.6 swdoccontentmgrinfo.srl:56
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:57'),  # spec 15.1.6 swdoccontentmgrinfo.srl:57
        ('put', 'u32', (0,), '15.1.6 swdoccontentmgrinfo.srl:58'),  # spec 15.1.6 swdoccontentmgrinfo.srl:58
        ('put', 'u32', (1,), '15.1.6 swdoccontentmgrinfo.srl:59'),  # spec 15.1.6 swdoccontentmgrinfo.srl:59
        ('put', 'cstr', ('Default',), '15.1.6 swdoccontentmgrinfo.srl:60'),  # spec 15.1.6 swdoccontentmgrinfo.srl:60
        ('put', 'u32', (0,), '15.1.6 swdoccontentmgrinfo.srl:61'),  # spec 15.1.6 swdoccontentmgrinfo.srl:61
    ),  # spec 15.1 swdoccontentmgrinfo.srl
    'ThirdPty/Animator': (  # spec 15.2 animator.srl
        ('put', 'u32', (17000,), '15.2.8 animator.srl:5'),  # spec 15.2.8 animator.srl:5
        ('archive', 'start', 1, '15.2.8 animator.srl:6'),  # spec 15.2.8 animator.srl:6
        ('class', 'moAnimationManager_c', 1, None, '15.2.8 animator.srl:7'),  # spec 15.2.8 animator.srl:7
        ('put', 'i32', (-1,), '15.2.8 animator.srl:8'),  # spec 15.2.8 animator.srl:8
        ('put', 'u32', (1,), '15.2.8 animator.srl:9'),  # spec 15.2.8 animator.srl:9
        ('class', 'moAnimKeyData_c', 1, None, '15.2.8 animator.srl:10'),  # spec 15.2.8 animator.srl:10
        ('put', 'cstr', ('Motion Study 1',), '15.2.8 animator.srl:11'),  # spec 15.2.8 animator.srl:11
        ('put', 'cstr', (('$', 'anim.guid'),), '15.2.8 animator.srl:12'),  # spec 15.2.8 animator.srl:12
        ('put', 'cstr', ('',), '15.2.8 animator.srl:13'),  # spec 15.2.8 animator.srl:13
        ('rep', 24, 0, '15.2.8 animator.srl:14'),  # spec 15.2.8 animator.srl:14
        ('put', 'i32', (-1,), '15.2.8 animator.srl:15'),  # spec 15.2.8 animator.srl:15
        ('put', 'u32', (6,), '15.2.8 animator.srl:16'),  # spec 15.2.8 animator.srl:16
        ('rep', 26, 0, '15.2.8 animator.srl:17'),  # spec 15.2.8 animator.srl:17
        ('put', 'f64', (-1.0, -1.0), '15.2.8 animator.srl:18'),  # spec 15.2.8 animator.srl:18
        ('rep', 33, 0, '15.2.8 animator.srl:19'),  # spec 15.2.8 animator.srl:19
        ('put', 'u32', (4,), '15.2.8 animator.srl:20'),  # spec 15.2.8 animator.srl:20
        ('rep', 6, 0, '15.2.8 animator.srl:21'),  # spec 15.2.8 animator.srl:21
        ('put', 'u32', (1,), '15.2.8 animator.srl:22'),  # spec 15.2.8 animator.srl:22
        ('rep', 12, 0, '15.2.8 animator.srl:23'),  # spec 15.2.8 animator.srl:23
        ('put', 'u16', (1,), '15.2.8 animator.srl:24'),  # spec 15.2.8 animator.srl:24
        ('put', 'cstr', ('Motion Study 1',), '15.2.8 animator.srl:25'),  # spec 15.2.8 animator.srl:25
    ),  # spec 15.2 animator.srl
    'ThirdPty/CMMotionLoadMapU': (  # spec 15.1 cmmotionloadmapu.srl
        ('put', 'u32', (1,), '15.1.7 cmmotionloadmapu.srl:5'),  # spec 15.1.7 cmmotionloadmapu.srl:5
        ('put', 'u32', (14,), '15.1.7 cmmotionloadmapu.srl:6'),  # spec 15.1.7 cmmotionloadmapu.srl:6
        ('put', 'utf16', ('Motion Study 1',), '15.1.7 cmmotionloadmapu.srl:7'),  # spec 15.1.7 cmmotionloadmapu.srl:7
        ('put', 'u32', (16,), '15.1.7 cmmotionloadmapu.srl:8'),  # spec 15.1.7 cmmotionloadmapu.srl:8
        ('put', 'latin1', ('CM_MOTION_LOAD_1',), '15.1.7 cmmotionloadmapu.srl:9'),  # spec 15.1.7 cmmotionloadmapu.srl:9
    ),  # spec 15.1 cmmotionloadmapu.srl
    'ThirdPty/CM_MOTION_LOAD_1': (  # spec 15.1 cm-motion-load-1.srl
    ),  # spec 15.1 cm-motion-load-1.srl
    'ThirdPty/SWA_Schedules': (  # spec 15.1 swa-schedules.srl
    ),  # spec 15.1 swa-schedules.srl
    'ThirdPtyStore/VisualStates': (  # spec 15.2 visualstates.srl
        ('put', 'u32', (17000,), '15.2.6.1 visualstates.srl:6'),  # spec 15.2.6.1 visualstates.srl:6
        ('put', 'u32', (0,), '15.2.6.1 visualstates.srl:7'),  # spec 15.2.6.1 visualstates.srl:7
        ('archive', 'start', 1, '15.2.6.1 visualstates.srl:8'),  # spec 15.2.6.1 visualstates.srl:8
        ('class', 'visStateKeyData_c', 1, None, '15.2.6.1 visualstates.srl:9'),  # spec 15.2.6.1 visualstates.srl:9
        ('put', 'u32', (5, 0, 1, 0, 1, 1, 1, 1), '15.2.6.1 visualstates.srl:10'),  # spec 15.2.6.1 visualstates.srl:10
        ('put', 'cstr', ('<Default>_Display State 1',), '15.2.6.1 visualstates.srl:11'),  # spec 15.2.6.1 visualstates.srl:11
        ('rep', 16, 0, '15.2.6.1 visualstates.srl:12'),  # spec 15.2.6.1 visualstates.srl:12
        ('put', 'u32', (('=', '5+len($sketches)'),), '15.2.6.1 visualstates.srl:13'),  # spec 15.2.6.1 visualstates.srl:13
        ('class', 'moCompHolder_c', 1, None, '15.2.6.2 visualstates.srl:24'),  # spec 15.2.6.2 visualstates.srl:24
        ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
        ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
        ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
        ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
        ('put', 'u32', (17000,), '15.2.6.2 visualstates.srl:26'),  # spec 15.2.6.2 visualstates.srl:26
        ('put', 'u32', (1, 1, 2), '15.2.6.2 visualstates.srl:27'),  # spec 15.2.6.2 visualstates.srl:27
        ('class', 'visStateVisualPropertiesAttribute_c', 1, None, '15.2.6.2 visualstates.srl:28'),  # spec 15.2.6.2 visualstates.srl:28
        ('put', 'u32', (1,), '15.2.6.2 visualstates.srl:29'),  # spec 15.2.6.2 visualstates.srl:29
        ('class', 'moVisualProperties_c', 1, None, '15.2.9 visual-properties.srl:5'),  # spec 15.2.9 visual-properties.srl:5
        ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:6'),  # spec 15.2.9 visual-properties.srl:6
        ('put', 'u32', (0, 0), '15.2.9 visual-properties.srl:7'),  # spec 15.2.9 visual-properties.srl:7
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:8'),  # spec 15.2.9 visual-properties.srl:8
        ('put', 'cstr', ('Steel',), '15.2.9 visual-properties.srl:9'),  # spec 15.2.9 visual-properties.srl:9
        ('put', 'f64', (1.0, 1.0, 0.5, 0.3125), '15.2.9 visual-properties.srl:10'),  # spec 15.2.9 visual-properties.srl:10
        ('rep', 20, 0, '15.2.9 visual-properties.srl:11'),  # spec 15.2.9 visual-properties.srl:11
        ('put', 'u32', (1, 0, 1, 1, 1), '15.2.9 visual-properties.srl:12'),  # spec 15.2.9 visual-properties.srl:12
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:13'),  # spec 15.2.9 visual-properties.srl:13
        ('put', 'u32', (1, 1, 33, 0), '15.2.9 visual-properties.srl:14'),  # spec 15.2.9 visual-properties.srl:14
        ('put', 'cstr', ('defaultplastic',), '15.2.9 visual-properties.srl:15'),  # spec 15.2.9 visual-properties.srl:15
        ('put', 'u8', (3,), '15.2.9 visual-properties.srl:16'),  # spec 15.2.9 visual-properties.srl:16
        ('put', 'u32', (15651274,), '15.2.9 visual-properties.srl:17'),  # spec 15.2.9 visual-properties.srl:17
        ('put', 'f32', (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0), '15.2.9 visual-properties.srl:18'),  # spec 15.2.9 visual-properties.srl:18
        ('put', 'u32', (1,), '15.2.9 visual-properties.srl:19'),  # spec 15.2.9 visual-properties.srl:19
        ('put', 'f32', (0.15, 0.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0), '15.2.9 visual-properties.srl:20'),  # spec 15.2.9 visual-properties.srl:20
        ('put', 'cstr', ('<SystemTexture>\\graphics\\materials\\color.p2m',), '15.2.9 visual-properties.srl:21'),  # spec 15.2.9 visual-properties.srl:21
        ('put', 'u32', (16777215,), '15.2.9 visual-properties.srl:22'),  # spec 15.2.9 visual-properties.srl:22
        ('put', 'f32', (0.6, 1.0), '15.2.9 visual-properties.srl:23'),  # spec 15.2.9 visual-properties.srl:23
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:24'),  # spec 15.2.9 visual-properties.srl:24
        ('put', 'f32', (0.001, 0.001, 0.0), '15.2.9 visual-properties.srl:25'),  # spec 15.2.9 visual-properties.srl:25
        ('put', 'u16', (320, 0), '15.2.9 visual-properties.srl:26'),  # spec 15.2.9 visual-properties.srl:26
        ('put', 'f32', (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 90.0, 1.0, -1.0, -1.0), '15.2.9 visual-properties.srl:27'),  # spec 15.2.9 visual-properties.srl:27
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:28'),  # spec 15.2.9 visual-properties.srl:28
        ('put', 'u32', (0,), '15.2.9 visual-properties.srl:29'),  # spec 15.2.9 visual-properties.srl:29
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:30'),  # spec 15.2.9 visual-properties.srl:30
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:31'),  # spec 15.2.9 visual-properties.srl:31
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:32'),  # spec 15.2.9 visual-properties.srl:32
        ('rep', 92, 0, '15.2.9 visual-properties.srl:33'),  # spec 15.2.9 visual-properties.srl:33
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:34'),  # spec 15.2.9 visual-properties.srl:34
        ('rep', 8, 0, '15.2.9 visual-properties.srl:35'),  # spec 15.2.9 visual-properties.srl:35
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:36'),  # spec 15.2.9 visual-properties.srl:36
        ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:37'),  # spec 15.2.9 visual-properties.srl:37
        ('put', 'cstr', ('',), '15.2.9 visual-properties.srl:38'),  # spec 15.2.9 visual-properties.srl:38
        ('put', 'u32', (0, 1), '15.2.9 visual-properties.srl:39'),  # spec 15.2.9 visual-properties.srl:39
        ('put', 'i32', (-1,), '15.2.9 visual-properties.srl:40'),  # spec 15.2.9 visual-properties.srl:40
        ('rep', 12, 0, '15.2.9 visual-properties.srl:41'),  # spec 15.2.9 visual-properties.srl:41
        ('class', 'visStateVisualStateAttribute_c', 1, 'shown', '15.2.6.2 visualstates.srl:31'),  # spec 15.2.6.2 visualstates.srl:31
        ('put', 'u32', (1, 1, 6, 1, 0), '15.2.6.2 visualstates.srl:32'),  # spec 15.2.6.2 visualstates.srl:32
        ('for', 'f', ('$', 'sketches'), True, (  # spec 15.2.6.3 visualstates.srl:45
            ('class', 'moCompFeature_c', 1, None, '15.2.6.3 visualstates.srl:38'),  # spec 15.2.6.3 visualstates.srl:38
            ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
            ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
            ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
            ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
            ('put', 'u32', (17000,), '15.2.6.3 visualstates.srl:40'),  # spec 15.2.6.3 visualstates.srl:40
            ('put', 'u32', (('$', 'f.id'),), '15.2.6.3 visualstates.srl:41'),  # spec 15.2.6.3 visualstates.srl:41
            ('put', 'u32', (('$', 'f.created'),), '15.2.6.3 visualstates.srl:42'),  # spec 15.2.6.3 visualstates.srl:42
            ('put', 'u32', (1, 1, 2), '15.2.6.3 visualstates.srl:43'),  # spec 15.2.6.3 visualstates.srl:43
            ('if', ('=', '$f_index==0'), (  # spec 15.2.6.3 visualstates.srl:47
                ('class', 'visStateVisualPropertiesAttribute_c', 1, 'plain', '15.2.6.3 visualstates.srl:48'),  # spec 15.2.6.3 visualstates.srl:48
                ('put', 'u32', (1,), '15.2.6.3 visualstates.srl:49'),  # spec 15.2.6.3 visualstates.srl:49
                ('put', 'u16', (0,), '15.2.6.3 visualstates.srl:50'),  # spec 15.2.6.3 visualstates.srl:50
            ), (  # spec 15.2.6.3 visualstates.srl:47
                ('objref', 'plain', '15.2.6.3 visualstates.srl:52'),  # spec 15.2.6.3 visualstates.srl:52
            ), '15.2.6.3 visualstates.srl:47'),  # spec 15.2.6.3 visualstates.srl:47
            ('objref', 'shown', '15.2.6.3 visualstates.srl:54'),  # spec 15.2.6.3 visualstates.srl:54
        ), '15.2.6.3 visualstates.srl:45'),  # spec 15.2.6.3 visualstates.srl:45
        ('class', 'moCompFeature_c', 1, None, '15.2.6.3 visualstates.srl:38'),  # spec 15.2.6.3 visualstates.srl:38
        ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
        ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
        ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
        ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
        ('put', 'u32', (17000,), '15.2.6.3 visualstates.srl:40'),  # spec 15.2.6.3 visualstates.srl:40
        ('put', 'u32', (5,), '15.2.6.3 visualstates.srl:41'),  # spec 15.2.6.3 visualstates.srl:41
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.6.3 visualstates.srl:42'),  # spec 15.2.6.3 visualstates.srl:42
        ('put', 'u32', (1, 1, 2), '15.2.6.3 visualstates.srl:43'),  # spec 15.2.6.3 visualstates.srl:43
        ('if', ('=', 'len($sketches)==0'), (  # spec 15.2.6.3 visualstates.srl:57
            ('class', 'visStateVisualPropertiesAttribute_c', 1, 'plain', '15.2.6.3 visualstates.srl:58'),  # spec 15.2.6.3 visualstates.srl:58
            ('put', 'u32', (1,), '15.2.6.3 visualstates.srl:59'),  # spec 15.2.6.3 visualstates.srl:59
            ('put', 'u16', (0,), '15.2.6.3 visualstates.srl:60'),  # spec 15.2.6.3 visualstates.srl:60
        ), (  # spec 15.2.6.3 visualstates.srl:57
            ('objref', 'plain', '15.2.6.3 visualstates.srl:62'),  # spec 15.2.6.3 visualstates.srl:62
        ), '15.2.6.3 visualstates.srl:57'),  # spec 15.2.6.3 visualstates.srl:57
        ('objref', 'shown', '15.2.6.3 visualstates.srl:64'),  # spec 15.2.6.3 visualstates.srl:64
        ('class', 'moCompFeature_c', 1, None, '15.2.6.3 visualstates.srl:38'),  # spec 15.2.6.3 visualstates.srl:38
        ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
        ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
        ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
        ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
        ('put', 'u32', (17000,), '15.2.6.3 visualstates.srl:40'),  # spec 15.2.6.3 visualstates.srl:40
        ('put', 'u32', (4,), '15.2.6.3 visualstates.srl:41'),  # spec 15.2.6.3 visualstates.srl:41
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.6.3 visualstates.srl:42'),  # spec 15.2.6.3 visualstates.srl:42
        ('put', 'u32', (1, 1, 2), '15.2.6.3 visualstates.srl:43'),  # spec 15.2.6.3 visualstates.srl:43
        ('objref', 'plain', '15.2.6.3 visualstates.srl:66'),  # spec 15.2.6.3 visualstates.srl:66
        ('class', 'visStateVisualStateAttribute_c', 1, 'hidden', '15.2.6.3 visualstates.srl:67'),  # spec 15.2.6.3 visualstates.srl:67
        ('put', 'u32', (1, 0, 6, 1, 0), '15.2.6.3 visualstates.srl:68'),  # spec 15.2.6.3 visualstates.srl:68
        ('class', 'moCompFeature_c', 1, None, '15.2.6.3 visualstates.srl:38'),  # spec 15.2.6.3 visualstates.srl:38
        ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
        ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
        ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
        ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
        ('put', 'u32', (17000,), '15.2.6.3 visualstates.srl:40'),  # spec 15.2.6.3 visualstates.srl:40
        ('put', 'u32', (3,), '15.2.6.3 visualstates.srl:41'),  # spec 15.2.6.3 visualstates.srl:41
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.6.3 visualstates.srl:42'),  # spec 15.2.6.3 visualstates.srl:42
        ('put', 'u32', (1, 1, 2), '15.2.6.3 visualstates.srl:43'),  # spec 15.2.6.3 visualstates.srl:43
        ('objref', 'plain', '15.2.6.3 visualstates.srl:70'),  # spec 15.2.6.3 visualstates.srl:70
        ('objref', 'hidden', '15.2.6.3 visualstates.srl:71'),  # spec 15.2.6.3 visualstates.srl:71
        ('class', 'moCompFeature_c', 1, None, '15.2.6.3 visualstates.srl:38'),  # spec 15.2.6.3 visualstates.srl:38
        ('class', 'moUnitComponent_c', 1, None, '15.2.6.1 visualstates.srl:17'),  # spec 15.2.6.1 visualstates.srl:17
        ('rep', 43, 0, '15.2.6.1 visualstates.srl:18'),  # spec 15.2.6.1 visualstates.srl:18
        ('put', 'i32', (-1, -1, -1, -1), '15.2.6.1 visualstates.srl:19'),  # spec 15.2.6.1 visualstates.srl:19
        ('rep', 20, 0, '15.2.6.1 visualstates.srl:20'),  # spec 15.2.6.1 visualstates.srl:20
        ('put', 'u32', (17000,), '15.2.6.3 visualstates.srl:40'),  # spec 15.2.6.3 visualstates.srl:40
        ('put', 'u32', (2,), '15.2.6.3 visualstates.srl:41'),  # spec 15.2.6.3 visualstates.srl:41
        ('put', 'u32', (('$', 'tpl.unix'),), '15.2.6.3 visualstates.srl:42'),  # spec 15.2.6.3 visualstates.srl:42
        ('put', 'u32', (1, 1, 2), '15.2.6.3 visualstates.srl:43'),  # spec 15.2.6.3 visualstates.srl:43
        ('objref', 'plain', '15.2.6.3 visualstates.srl:73'),  # spec 15.2.6.3 visualstates.srl:73
        ('objref', 'hidden', '15.2.6.3 visualstates.srl:74'),  # spec 15.2.6.3 visualstates.srl:74
        ('put', 'u16', (0,), '15.2.6.3 visualstates.srl:75'),  # spec 15.2.6.3 visualstates.srl:75
        ('rep', 6, 0, '15.2.6.3 visualstates.srl:76'),  # spec 15.2.6.3 visualstates.srl:76
    ),  # spec 15.2 visualstates.srl
    '[Content_Types].xml': (  # spec 15.1 content-types.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.3 content-types.srl:4
            ('<?xml version="1.0"?>',),  # spec 15.1.3 content-types.srl:4
            ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/></Types>',),  # spec 15.1.3 content-types.srl:4
        ), '15.1.3 content-types.srl:4'),  # spec 15.1.3 content-types.srl:4
    ),  # spec 15.1 content-types.srl
    '_DL_VERSION_17000/DLUpdateStamp': (  # spec 15.1 dlupdatestamp.srl
        ('put', 'u32', (('$', 'doc.stamp'),), '15.1.7 dlupdatestamp.srl:4'),  # spec 15.1.7 dlupdatestamp.srl:4
        ('put', 'u16', (0,), '15.1.7 dlupdatestamp.srl:5'),  # spec 15.1.7 dlupdatestamp.srl:5
    ),  # spec 15.1 dlupdatestamp.srl
    '_MO_VERSION_17000/Biography': (  # spec 15.2 biography.srl
        ('archive', 'start', 1, '15.2.10.1 biography.srl:5'),  # spec 15.2.10.1 biography.srl:5
        ('class', 'moBiography_c', 1, None, '15.2.10.1 biography.srl:6'),  # spec 15.2.10.1 biography.srl:6
        ('put', 'u32', (2,), '15.2.10.1 biography.srl:7'),  # spec 15.2.10.1 biography.srl:7
        ('put', 'u32', (17000,), '15.2.10.1 biography.srl:11'),  # spec 15.2.10.1 biography.srl:11
        ('put', 'u32', (2024016,), '15.2.10.1 biography.srl:12'),  # spec 15.2.10.1 biography.srl:12
        ('put', 'u32', (1, 9, 12), '15.2.10.1 biography.srl:13'),  # spec 15.2.10.1 biography.srl:13
        ('put', 'u32', (('$', 'bio.os.platform'),), '15.2.10.1 biography.srl:14'),  # spec 15.2.10.1 biography.srl:14
        ('put', 'u32', (('$', 'bio.os.major'),), '15.2.10.1 biography.srl:15'),  # spec 15.2.10.1 biography.srl:15
        ('put', 'u32', (('$', 'bio.os.minor'),), '15.2.10.1 biography.srl:16'),  # spec 15.2.10.1 biography.srl:16
        ('put', 'u32', (('$', 'bio.os.build'),), '15.2.10.1 biography.srl:17'),  # spec 15.2.10.1 biography.srl:17
        ('put', 'cstr', ('',), '15.2.10.1 biography.srl:18'),  # spec 15.2.10.1 biography.srl:18
        ('put', 'u16', (('$', 'bio.locale'),), '15.2.10.1 biography.srl:19'),  # spec 15.2.10.1 biography.srl:19
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:32'),  # spec 15.2.10.2 biography.srl:32
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:33'),  # spec 15.2.10.2 biography.srl:33
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:34'),  # spec 15.2.10.2 biography.srl:34
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:35'),  # spec 15.2.10.2 biography.srl:35
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:36'),  # spec 15.2.10.2 biography.srl:36
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:37'),  # spec 15.2.10.2 biography.srl:37
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:38'),  # spec 15.2.10.2 biography.srl:38
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:39'),  # spec 15.2.10.2 biography.srl:39
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:40'),  # spec 15.2.10.2 biography.srl:40
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:41'),  # spec 15.2.10.2 biography.srl:41
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:42'),  # spec 15.2.10.2 biography.srl:42
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:43'),  # spec 15.2.10.2 biography.srl:43
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:44'),  # spec 15.2.10.2 biography.srl:44
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:45'),  # spec 15.2.10.2 biography.srl:45
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:46'),  # spec 15.2.10.2 biography.srl:46
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:47'),  # spec 15.2.10.2 biography.srl:47
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:48'),  # spec 15.2.10.2 biography.srl:48
        ('put', 'cstr', ('',), '15.2.10.2 biography.srl:49'),  # spec 15.2.10.2 biography.srl:49
        ('put', 'u32', (0,), '15.2.10.2 biography.srl:50'),  # spec 15.2.10.2 biography.srl:50
        ('put', 'u64', (0,), '15.2.10.2 biography.srl:51'),  # spec 15.2.10.2 biography.srl:51
        ('put', 'u64', (('$', 'bio.made.time'),), '15.2.10.2 biography.srl:52'),  # spec 15.2.10.2 biography.srl:52
        ('put', 'u32', (('$', 'bio.made.tag'),), '15.2.10.2 biography.srl:53'),  # spec 15.2.10.2 biography.srl:53
        ('put', 'cstr', (('$', 'bio.made.system'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.made.windows'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.made.work'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.made.temp'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.made.temp'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.made.template'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.made.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'u32', (17000,), '15.2.10.1 biography.srl:11'),  # spec 15.2.10.1 biography.srl:11
        ('put', 'u32', (2024016,), '15.2.10.1 biography.srl:12'),  # spec 15.2.10.1 biography.srl:12
        ('put', 'u32', (1, 9, 12), '15.2.10.1 biography.srl:13'),  # spec 15.2.10.1 biography.srl:13
        ('put', 'u32', (('$', 'bio.os.platform'),), '15.2.10.1 biography.srl:14'),  # spec 15.2.10.1 biography.srl:14
        ('put', 'u32', (('$', 'bio.os.major'),), '15.2.10.1 biography.srl:15'),  # spec 15.2.10.1 biography.srl:15
        ('put', 'u32', (('$', 'bio.os.minor'),), '15.2.10.1 biography.srl:16'),  # spec 15.2.10.1 biography.srl:16
        ('put', 'u32', (('$', 'bio.os.build'),), '15.2.10.1 biography.srl:17'),  # spec 15.2.10.1 biography.srl:17
        ('put', 'cstr', ('',), '15.2.10.1 biography.srl:18'),  # spec 15.2.10.1 biography.srl:18
        ('put', 'u16', (('$', 'bio.locale'),), '15.2.10.1 biography.srl:19'),  # spec 15.2.10.1 biography.srl:19
        ('put', 'u64', (('$', 'bio.open.time'),), '15.2.10.3 biography.srl:64'),  # spec 15.2.10.3 biography.srl:64
        ('put', 'u32', (('$', 'bio.open.tag'),), '15.2.10.3 biography.srl:65'),  # spec 15.2.10.3 biography.srl:65
        ('put', 'cstr', (('$', 'bio.open.system'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.open.windows'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.open.work'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.open.temp'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.open.temp'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.open.template'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.open.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'u64', (('$', 'bio.save.time'),), '15.2.10.3 biography.srl:72'),  # spec 15.2.10.3 biography.srl:72
        ('put', 'u32', (('$', 'bio.save.tag'),), '15.2.10.3 biography.srl:73'),  # spec 15.2.10.3 biography.srl:73
        ('put', 'cstr', ('*',), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', ('*',), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.save.folder'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', ('*',), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', ('*',), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
        ('put', 'cstr', (('$', 'bio.save.file'),), '15.2.10.1 biography.srl:24'),  # spec 15.2.10.1 biography.srl:24
        ('put', 'u32', (3,), '15.2.10.1 biography.srl:25'),  # spec 15.2.10.1 biography.srl:25
        ('put', 'u64', (('$', 'bio.save.x'),), '15.2.10.1 biography.srl:26'),  # spec 15.2.10.1 biography.srl:26
    ),  # spec 15.2 biography.srl
    '_MO_VERSION_17000/History': (  # spec 15.1 history.srl
        ('class', 'moVersionHistory_c', 1, None, '15.1.7 history.srl:5'),  # spec 15.1.7 history.srl:5
        ('put', 'u32', (1,), '15.1.7 history.srl:6'),  # spec 15.1.7 history.srl:6
        ('put', 'u16', (0, 0, 0), '15.1.7 history.srl:7'),  # spec 15.1.7 history.srl:7
        ('put', 'u32', (1711409212,), '15.1.7 history.srl:8'),  # spec 15.1.7 history.srl:8
        ('put', 'cstr', ('',), '15.1.7 history.srl:9'),  # spec 15.1.7 history.srl:9
        ('put', 'u32', (17000,), '15.1.7 history.srl:10'),  # spec 15.1.7 history.srl:10
        ('class', 'moDateCodeHistory_c', 1, None, '15.1.7 history.srl:11'),  # spec 15.1.7 history.srl:11
        ('put', 'u32', (1,), '15.1.7 history.srl:12'),  # spec 15.1.7 history.srl:12
        ('put', 'u32', (18801232,), '15.1.7 history.srl:13'),  # spec 15.1.7 history.srl:13
        ('put', 'u32', (0,), '15.1.7 history.srl:14'),  # spec 15.1.7 history.srl:14
        ('put', 'u32', (4294967295,), '15.1.7 history.srl:15'),  # spec 15.1.7 history.srl:15
        ('rep', 14, 0, '15.1.7 history.srl:16'),  # spec 15.1.7 history.srl:16
    ),  # spec 15.1 history.srl
    '_rels/.rels': (  # spec 15.1 rels.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.3 rels.srl:4
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.3 rels.srl:4
            ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/></Relationships>',),  # spec 15.1.3 rels.srl:4
        ), '15.1.3 rels.srl:4'),  # spec 15.1.3 rels.srl:4
    ),  # spec 15.1 rels.srl
    'docProps/Config-0-Properties.xml': (  # spec 15.1 config-0-properties.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 config-0-properties.srl:5
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 config-0-properties.srl:5
            ('<ConfigProperties xmlns="http://www.solidworks.com/config-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><propertySection xmlns="" name="DocumentSummaryInformation" fmtid="{D5CDD502-2E9C-101B-9397-08002B2CF9AE}"><propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement></propertySection><propertySection xmlns="" name="UserDefinedProperties" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"><property name="" pid="1" TypeID="0"><vt:i2>65001</vt:i2></property><propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement></propertySection></ConfigProperties>',),  # spec 15.1.4 config-0-properties.srl:5
        ), '15.1.4 config-0-properties.srl:5'),  # spec 15.1.4 config-0-properties.srl:5
    ),  # spec 15.1 config-0-properties.srl
    'docProps/ISolidWorksInformation.xml': (  # spec 15.1 isolidworksinformation.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 isolidworksinformation.srl:5
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 isolidworksinformation.srl:5
            ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/SolidworksInformation-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><propertySection xmlns="" name="UserDefinedProperties" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"><property name="" pid="1"><vt:i2>65001</vt:i2></property><property name="SW-File Name" pid="3"><vt:lpstr>', ('$', 'meta.file_stem'), '</vt:lpstr></property><property name="SW-BOM Part Number" pid="4"><vt:lpstr>', ('$', 'doc.name'), '</vt:lpstr></property><property name="SW-Folder Name" pid="5"><vt:lpstr></vt:lpstr></property><property name="SW-Short Date" pid="6"><vt:lpstr>', ('$', 'meta.short_date'), '</vt:lpstr></property><property name="SW-Long Date" pid="7"><vt:lpstr>', ('$', 'meta.long_date'), '</vt:lpstr></property><property name="SW-Configuration Name" pid="8"><vt:lpstr>Default</vt:lpstr></property><property name="SW-Author" pid="9"><vt:lpstr></vt:lpstr></property><property name="SW-Keywords" pid="10"><vt:lpstr></vt:lpstr></property><property name="SW-Comments" pid="11"><vt:lpstr></vt:lpstr></property><property name="SW-Title" pid="12"><vt:lpstr></vt:lpstr></property><property name="SW-Subject" pid="13"><vt:lpstr></vt:lpstr></property><property name="SW-Created Date" pid="14"><vt:lpstr>', ('$', 'meta.created_text'), '</vt:lpstr></property><property name="SW-Last Saved Date" pid="15"><vt:lpstr>', ('$', 'meta.saved_text'), '</vt:lpstr></property><property name="SW-Last Saved By" pid="16"><vt:lpstr>', ('$', 'doc.author'), '</vt:lpstr></property><property name="SW-File Title" pid="17"><vt:lpstr>', ('$', 'meta.file_stem'), '</vt:lpstr></property><property name="SW-HasDesignTable" pid="18"><vt:i4>0</vt:i4></property><property name="IsCPReArchEnabled" pid="19"><vt:i4>1</vt:i4></property><property name="SW_UnitSystem" pid="20"><vt:i4>5</vt:i4></property><property name="SW_UnitsLinear" pid="21"><vt:i4>0</vt:i4></property><property name="SW_UnitsLinearDecimalDisplay" pid="22"><vt:i4>1</vt:i4></property><property name="SW_UnitsLinearDecimalPlaces" pid="23"><vt:i4>2</vt:i4></property><property name="SW_UnitsLinearFractionDenominator" pid="24"><vt:i4>0</vt:i4></property><property name="SW_UnitsDualLinear" pid="25"><vt:i4>3</vt:i4></property><property name="SW_UnitsTimeUnits" pid="26"><vt:i4>1</vt:i4></property><property name="SW_UnitsPowerUnits" pid="27"><vt:i4>1</vt:i4></property><property name="SW_UnitsEnergyUnits" pid="28"><vt:i4>1</vt:i4></property><property name="SW_UnitsDualLinearDecimalDisplay" pid="29"><vt:i4>1</vt:i4></property><property name="SW_UnitsDualLinearDecimalPlaces" pid="30"><vt:i4>2</vt:i4></property><property name="SW_UnitsDualLinearFractionDenominator" pid="31"><vt:i4>2</vt:i4></property><property name="SW_UnitsAngular" pid="32"><vt:i4>0</vt:i4></property><property name="SW_UnitsAngularDecimalPlaces" pid="33"><vt:i4>2</vt:i4></property><property name="SW_UnitsMassPropLength" pid="34"><vt:i4>0</vt:i4></property><property name="SW_UnitsMassPropDecimalPlaces" pid="35"><vt:i4>2</vt:i4></property><property name="SW_UnitsMassPropMass" pid="36"><vt:i4>2</vt:i4></property><property name="SW_UnitsMassPropVolume" pid="37"><vt:i4>4</vt:i4></property><property name="SW_UnitsTimeDecimalPlaces" pid="38"><vt:i4>2</vt:i4></property><property name="SW_UnitsForce" pid="39"><vt:i4>3</vt:i4></property><property name="SW_UnitsForceDecimalPlaces" pid="40"><vt:i4>2</vt:i4></property><property name="SW_UnitsPowerDecimalPlaces" pid="41"><vt:i4>2</vt:i4></property><property name="SW_UnitsEnergyDecimalPlaces" pid="42"><vt:i4>2</vt:i4></property><property name="SW_UnitsDecimalRounding" pid="43"><vt:i4>0</vt:i4></property><property name="SW_UnitsLinearFeetAndInchesFormat" pid="44"><vt:i4>1</vt:i4></property><property name="SW_UnitsLinearRoundToNearestFraction" pid="45"><vt:i4>0</vt:i4></property><property name="SW_UnitsDualLinearRoundToNearestFraction" pid="46"><vt:i4>0</vt:i4></property><property name="SW_UnitsDualLinearFeetAndInchesFormat" pid="47"><vt:i4>1</vt:i4></property><property name="Component Type" pid="48"><vt:i4>0</vt:i4></property><propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement><propertyNameDictionaryElement name="Component Type" pid="48"></propertyNameDictionaryElement><propertyNameDictionaryElement name="IsCPReArchEnabled" pid="19"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Author" pid="9"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Author(Author)" pid="9"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-BOM Part Number" pid="4"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-BOM Part Number(BOM Part Number)" pid="4"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Comments" pid="11"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Comments(Comments)" pid="11"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Configuration Name" pid="8"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Configuration Name(Configuration Name)" pid="8"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Created Date" pid="14"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Created Date(Created Date)" pid="14"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-File Name" pid="3"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-File Name(File Name)" pid="3"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-File Title" pid="17"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-File Title(File Title)" pid="17"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Folder Name" pid="5"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Folder Name(Folder Name)" pid="5"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-HasDesignTable" pid="18"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Keywords" pid="10"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Keywords(Keywords)" pid="10"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Last Saved By" pid="16"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Last Saved By(Last Saved By)" pid="16"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Last Saved Date" pid="15"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Last Saved Date(Last Saved Date)" pid="15"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Long Date" pid="7"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Long Date(Long Date)" pid="7"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Short Date" pid="6"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Short Date(Short Date)" pid="6"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Subject" pid="13"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Subject(Subject)" pid="13"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Title" pid="12"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW-Title(Title)" pid="12"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsAngular" pid="32"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsAngularDecimalPlaces" pid="33"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDecimalRounding" pid="43"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinear" pid="25"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinearDecimalDisplay" pid="29"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinearDecimalPlaces" pid="30"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinearFeetAndInchesFormat" pid="47"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinearFractionDenominator" pid="31"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsDualLinearRoundToNearestFraction" pid="46"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsEnergyDecimalPlaces" pid="42"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsEnergyUnits" pid="28"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsForce" pid="39"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsForceDecimalPlaces" pid="40"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinear" pid="21"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinearDecimalDisplay" pid="22"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinearDecimalPlaces" pid="23"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinearFeetAndInchesFormat" pid="44"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinearFractionDenominator" pid="24"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsLinearRoundToNearestFraction" pid="45"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsMassPropDecimalPlaces" pid="35"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsMassPropLength" pid="34"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsMassPropMass" pid="36"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsMassPropVolume" pid="37"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsPowerDecimalPlaces" pid="41"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsPowerUnits" pid="27"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsTimeDecimalPlaces" pid="38"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitsTimeUnits" pid="26"></propertyNameDictionaryElement><propertyNameDictionaryElement name="SW_UnitSystem" pid="20"></propertyNameDictionaryElement></propertySection></Properties>'),  # spec 15.1.4 isolidworksinformation.srl:5
        ), '15.1.4 isolidworksinformation.srl:5'),  # spec 15.1.4 isolidworksinformation.srl:5
    ),  # spec 15.1 isolidworksinformation.srl
    'docProps/OpenTime.xml': (  # spec 15.1 opentime.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 opentime.srl:4
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 opentime.srl:4
            ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/SolidworksOpenTime" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><count xmlns="">0</count><TotalFileOpenTime xmlns="">-1</TotalFileOpenTime><LWcount xmlns="">0</LWcount><LWTotalFileOpenTime xmlns="">-1</LWTotalFileOpenTime></Properties>',),  # spec 15.1.4 opentime.srl:4
        ), '15.1.4 opentime.srl:4'),  # spec 15.1.4 opentime.srl:4
    ),  # spec 15.1 opentime.srl
    'docProps/app.xml': (  # spec 15.1 app.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 app.srl:4
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 app.srl:4
            ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Template>Normal.dotm</Template><TotalTime>', ('$', 'meta.total_time'), '</TotalTime><Application>SOLIDWORKS</Application><DocSecurity>0</DocSecurity><Company>', ('$', 'meta.company'), '</Company><LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged><AppVersion>23.0000</AppVersion></Properties>'),  # spec 15.1.4 app.srl:4
        ), '15.1.4 app.srl:4'),  # spec 15.1.4 app.srl:4
    ),  # spec 15.1 app.srl
    'docProps/core.xml': (  # spec 15.1 core.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 core.srl:4
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 core.srl:4
            ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:lastModifiedBy>', ('$', 'doc.author'), '</dc:lastModifiedBy><dcterms:created>', ('$', 'meta.created_iso'), '</dcterms:created><dcterms:modified>', ('$', 'doc.iso'), '</dcterms:modified></cp:coreProperties>'),  # spec 15.1.4 core.srl:4
        ), '15.1.4 core.srl:4'),  # spec 15.1.4 core.srl:4
    ),  # spec 15.1 core.srl
    'docProps/custom.xml': (  # spec 15.1 custom.srl
        ('text', 'utf8', 'crlf', False, False, (  # spec 15.1.4 custom.srl:10
            ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',),  # spec 15.1.4 custom.srl:10
            ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><propertySection xmlns="" name="DocumentSummaryInformation" fmtid="{D5CDD502-2E9C-101B-9397-08002B2CF9AE}"><property name="" pid="1" TypeID="0"><vt:i2>65001</vt:i2></property><property name="" pid="22" TypeID="0"><vt:bool>No</vt:bool></property><propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement></propertySection><propertySection xmlns="" name="UserDefinedProperties" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"><property name="" pid="1" TypeID="0"><vt:i2>65001</vt:i2></property><propertyNameDictionaryElement name="" pid="0"></propertyNameDictionaryElement>',),  # spec 15.1.4 custom.srl:10
        ), '15.1.4 custom.srl:10'),  # spec 15.1.4 custom.srl:10
        ('for', 'p', ('$', 'props_by_name'), False, (  # spec 15.1.4 custom.srl:14
            ('text', 'utf8', 'lf', False, False, (  # spec 15.1.4 custom.srl:15
                ('<propertyNameDictionaryElement name="', ('$', 'p.name'), '" pid="', ('$', 'p.pid'), '"></propertyNameDictionaryElement>'),  # spec 15.1.4 custom.srl:15
            ), '15.1.4 custom.srl:15'),  # spec 15.1.4 custom.srl:15
        ), '15.1.4 custom.srl:14'),  # spec 15.1.4 custom.srl:14
        ('for', 'p', ('$', 'props'), False, (  # spec 15.1.4 custom.srl:19
            ('if', ('=', '$p.code==0'), (  # spec 15.1.4 custom.srl:20
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.4 custom.srl:21
                    ('<property name="', ('$', 'p.name'), '" pid="', ('$', 'p.pid'), '" IsEquation="False" TypeID="', ('$', 'p.type_id'), '"><vt:', ('$', 'p.vt'), '>'),  # spec 15.1.4 custom.srl:21
                ), '15.1.4 custom.srl:21'),  # spec 15.1.4 custom.srl:21
            ), (  # spec 15.1.4 custom.srl:20
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.4 custom.srl:25
                    ('<property name="', ('$', 'p.name'), '" pid="', ('$', 'p.pid'), '" TypeID="', ('$', 'p.type_id'), '"><vt:', ('$', 'p.vt'), '>'),  # spec 15.1.4 custom.srl:25
                ), '15.1.4 custom.srl:25'),  # spec 15.1.4 custom.srl:25
            ), '15.1.4 custom.srl:20'),  # spec 15.1.4 custom.srl:20
            ('put', 'utf8', (('$', 'p.xml_value'),), '15.1.4 custom.srl:29'),  # spec 15.1.4 custom.srl:29
            ('text', 'utf8', 'lf', False, False, (  # spec 15.1.4 custom.srl:30
                ('</vt:', ('$', 'p.vt'), '><FPVals><vt:', ('$', 'p.vt'), '>'),  # spec 15.1.4 custom.srl:30
            ), '15.1.4 custom.srl:30'),  # spec 15.1.4 custom.srl:30
            ('put', 'utf8', (('$', 'p.xml_text'),), '15.1.4 custom.srl:33'),  # spec 15.1.4 custom.srl:33
            ('text', 'utf8', 'lf', False, False, (  # spec 15.1.4 custom.srl:34
                ('</vt:', ('$', 'p.vt'), '></FPVals></property>'),  # spec 15.1.4 custom.srl:34
            ), '15.1.4 custom.srl:34'),  # spec 15.1.4 custom.srl:34
        ), '15.1.4 custom.srl:19'),  # spec 15.1.4 custom.srl:19
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.4 custom.srl:38
            ('</propertySection></Properties>',),  # spec 15.1.4 custom.srl:38
        ), '15.1.4 custom.srl:38'),  # spec 15.1.4 custom.srl:38
    ),  # spec 15.1 custom.srl
    'swXmlContents/Features': (  # spec 15.1 features-xml.srl
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.5 features-xml.srl:5
            ('<?xml version="1.0" encoding="UTF-8"?>',),  # spec 15.1.5 features-xml.srl:5
            ('<swSolidWorks xmlns="http://www.solidworks.com/sw2003/schema" swObjCount="3" swVersion="17000"><swHeader swObjCount="1"><swFile id="3" swDocType="PART" swCreationTime="', ('$', 'doc.created'), '" swPath="', ('$', 'meta.file_stem'), '.sldprt"/></swHeader><swModelList swObjCount="1"><swModel id="2" swName="', ('$', 'meta.file_stem'), '" swConfigurationName="Default" swConfigurationId="0" swLastModifiedStamp="', ('$', 'doc.stamp'), '" swConfigurationFlags="-2143288960" swFileRef="3"/></swModelList><swConfigurationList swObjCount="1"><swConfiguration id="1" swName="Default" swID="0" swReference="', ('$', 'doc.name'), '" swMostRecentConfiguration="YES" swConfigurationNeedsUpdate="NO" swDefeatureConfiguration="NO" swModelRef="2"/></swConfigurationList><swExtFeatureList swObjCount="0"/></swSolidWorks>'),  # spec 15.1.5 features-xml.srl:5
        ), '15.1.5 features-xml.srl:5'),  # spec 15.1.5 features-xml.srl:5
    ),  # spec 15.1 features-xml.srl
    'swXmlContents/KeyWords': (  # spec 15.1 keywords.srl
        ('hex', '86', '15.1.5 keywords.srl:7'),  # spec 15.1.5 keywords.srl:7
        ('text', 'utf8', 'crlf', False, False, (  # spec 15.1.5 keywords.srl:8
            ('<?xml version="1.0" encoding="UTF-8"?>',),  # spec 15.1.5 keywords.srl:8
            ('<Keywords id="', ('$', 'doc.created'), '" Name="', ('$', 'doc.name'), '"><Configuration id="0" Name="Default" Type="ConfigurationManager" Material="Material &lt;not specified&gt;"/>'),  # spec 15.1.5 keywords.srl:8
        ), '15.1.5 keywords.srl:8'),  # spec 15.1.5 keywords.srl:8
        ('for', 'e', ('$', 'meta.kw_extrusions'), False, (  # spec 15.1.5 keywords.srl:12
            ('if', ('$', 'e.first'), (  # spec 15.1.5 keywords.srl:13
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.5 keywords.srl:14
                    ('<Extrusion id="', ('$', 'e.id'), '" Name="', ('$', 'e.name'), '" Type="Boss-Extrude"><Dimension Name="D1">', ('$', 'e.depth_text'), '</Dimension></Extrusion>'),  # spec 15.1.5 keywords.srl:14
                ), '15.1.5 keywords.srl:14'),  # spec 15.1.5 keywords.srl:14
            ), (  # spec 15.1.5 keywords.srl:13
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.5 keywords.srl:18
                    ('<Extrusion id="', ('$', 'e.id'), '" Name="', ('$', 'e.name'), '" Dissectable="true" DissectableChildren="', ('$', 'e.sketch_id'), '" DissectableRoot="true"><Dimension Name="D1">', ('$', 'e.depth_text'), '</Dimension></Extrusion>'),  # spec 15.1.5 keywords.srl:18
                ), '15.1.5 keywords.srl:18'),  # spec 15.1.5 keywords.srl:18
            ), '15.1.5 keywords.srl:13'),  # spec 15.1.5 keywords.srl:13
        ), '15.1.5 keywords.srl:12'),  # spec 15.1.5 keywords.srl:12
        ('text', 'utf8', 'lf', False, False, (  # spec 15.1.5 keywords.srl:24
            ('<Feature id="1" Name="Annotations" Type="Annotations"/><Feature id="10" Name="Surface Bodies" Type="Surface Bodies"/><Feature id="11" Name="Material &lt;not specified&gt;" Type="SOLIDWORKS Materials"/><Feature id="12" Name="Ambient" Type="Ambient"/><Feature id="13" Name="Directional1" Type="Directional"/><Feature id="14" Name="Directional2" Type="Directional"/><Feature id="15" Name="Directional3" Type="Directional"/><Feature id="16" Name="Equations" Type="Equations"/><Feature id="17" Name="Notes" Type="Notes"/><Feature id="18" Name="Notes1___EndTag___" Type="Notes"/><Feature id="19" Name="" Type="Exploded Views"/><Feature id="2" Name="Front Plane" Type="Plane"/><Feature id="21" Name="Markups" Type="Markups"/><Feature id="22" Name="Sensors" Type="Sensors"/><Feature id="23" Name="Favorites" Type="Favorites"/><Feature id="24" Name="Folder " Type="History"/><Feature id="25" Name="Selection Sets" Type="Selection Sets"/><Feature id="3" Name="Top Plane" Type="Plane"/><Feature id="4" Name="Right Plane" Type="Plane"/><Feature id="6" Name="Lights and Cameras" Type="Lights and Cameras"/><Feature id="7" Name="Design Binder" Type="Design Binder"/><Feature id="8" Name="Comments" Type="Comments"/><Feature id="9" Name="Solid Bodies" Type="Solid Bodies"/>',),  # spec 15.1.5 keywords.srl:24
        ), '15.1.5 keywords.srl:24'),  # spec 15.1.5 keywords.srl:24
        ('for', 's', ('$', 'meta.kw_sketches'), False, (  # spec 15.1.5 keywords.srl:28
            ('if', ('$', 's.origin'), (  # spec 15.1.5 keywords.srl:29
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.5 keywords.srl:30
                    ('<Sketch id="5" Name="Origin" Type="Origin"/>',),  # spec 15.1.5 keywords.srl:30
                ), '15.1.5 keywords.srl:30'),  # spec 15.1.5 keywords.srl:30
            ), (  # spec 15.1.5 keywords.srl:29
                ('text', 'utf8', 'lf', False, False, (  # spec 15.1.5 keywords.srl:34
                    ('<Sketch id="', ('$', 's.id'), '" Name="', ('$', 's.name'), '" Dissectable="true"/>'),  # spec 15.1.5 keywords.srl:34
                ), '15.1.5 keywords.srl:34'),  # spec 15.1.5 keywords.srl:34
            ), '15.1.5 keywords.srl:29'),  # spec 15.1.5 keywords.srl:29
        ), '15.1.5 keywords.srl:28'),  # spec 15.1.5 keywords.srl:28
        ('text', 'utf8', 'crlf', True, False, (  # spec 15.1.5 keywords.srl:39
            ('</Keywords>',),  # spec 15.1.5 keywords.srl:39
        ), '15.1.5 keywords.srl:39'),  # spec 15.1.5 keywords.srl:39
    ),  # spec 15.1 keywords.srl
}
