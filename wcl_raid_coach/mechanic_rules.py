from __future__ import annotations

from dataclasses import dataclass


RULESET_VERSION = "12.1.0.69587-2026-09-02"
ZONE_ID = 53
DIFFICULTIES = (3, 4, 5)

RAID_ENCOUNTERS = (
    (3470, "Nek'zali the Soulcoiler", "盘魂者内克扎莉"),
    (3445, "Entombed Sentinels", "陵寝哨兵"),
    (3455, "Vashnik the Malignant", "万毒邪祟者瓦什尼克"),
    (3497, "The Lost Explorers", "迷失的探险者"),
    (3420, "Sszorak", "斯索拉克"),
    (3421, "The Twin Fangs", "双子毒牙"),
    (3429, "The Coiled Altar", "盘曲祭坛"),
    (3492, "Ula'tek", "乌拉泰克"),
)

RULESET_SOURCES = (
    "https://worldofwarcraft.blizzard.com/en-gb/news/24294062/curse-of-ulatek-the-venomous-abyss-raid-goes-live-19-august",
    "https://worldofwarcraft.blizzard.com/en-us/news/24296142/hotfixes-september-1-2026",
    "https://www.warcraftlogs.com/v2-api-docs/warcraft/report.doc.html",
    "https://wago.tools/db2/SpellName/csv?locale=zhCN",
)

Signal = tuple[int, tuple[str, ...]]


@dataclass(frozen=True)
class MechanicRule:
    rule_id: str
    encounter_id: int
    name_en: str
    name_zh: str
    difficulties: tuple[int, ...]
    ability_ids: tuple[int, ...]
    failure_signals: tuple[Signal, ...] = ()
    opportunity_signals: tuple[Signal, ...] = ()
    success_signals: tuple[Signal, ...] = ()
    scope: str = "target"
    evaluation: str = "signals"
    verified_difficulties: tuple[int, ...] = ()
    expectation: str = ""


def _signal(ability_id: int, *event_types: str) -> Signal:
    return ability_id, event_types


def _rule(
    rule_id: str,
    encounter_id: int,
    name_en: str,
    name_zh: str,
    ability_ids: tuple[int, ...],
    *,
    difficulties: tuple[int, ...] = DIFFICULTIES,
    failure: tuple[Signal, ...] = (),
    opportunity: tuple[Signal, ...] = (),
    success: tuple[Signal, ...] = (),
    scope: str = "target",
    evaluation: str = "signals",
    verified: tuple[int, ...] | None = None,
    expectation: str = "",
) -> MechanicRule:
    return MechanicRule(
        rule_id,
        encounter_id,
        name_en,
        name_zh,
        difficulties,
        ability_ids,
        failure,
        opportunity,
        success,
        scope,
        evaluation,
        difficulties if verified is None else verified,
        expectation,
    )


RULES = (
    # Nek'zali the Soulcoiler
    _rule("NEK-ENRAGE", 3470, "Uncoiled Rage", "溃散之怒", (1284034,), failure=(_signal(1284034, "applybuff"),), scope="team", expectation="Do not let Nek'zali reach full energy."),
    _rule("NEK-AMANI-RITE", 3470, "Gravebound Advance", "墓缚推进", (1287533, 1288772, 1285681, 1299673), evaluation="observation", expectation="Defeat Restless Amani before they reach the Soulcoil Well."),
    _rule("NEK-VESSEL", 3470, "Vessel of Awakening", "觉醒宿主", (1297630, 1297631), failure=(_signal(1297630), _signal(1297631)), scope="team", difficulties=(4, 5), expectation="Prevent a Restless Amani corpse from reawakening."),
    _rule("NEK-ANGUISHED", 3470, "Anguished Echoes", "苦痛回响", (1285681, 1294846), failure=(_signal(1294846, "damage"),), opportunity=(_signal(1285681, "cast"),), expectation="Avoid contact with Anguished Echoes."),
    _rule("NEK-ESSENCE", 3470, "Essence Rend", "精华撕裂", (1287434, 1288554), failure=(_signal(1288554, "damage"),), expectation="Avoid contact with the Latent Cultist created by Essence Rend."),
    _rule("NEK-POSSESSION", 3470, "Possession Barrage", "附身弹幕", (1284103, 1292034), evaluation="observation", expectation="Spread the barrage damage as required by the encounter."),
    _rule("NEK-HOLLOWING", 3470, "Hollowing Strikes", "摄魂打击", (1284109,), evaluation="observation", expectation="Track tank stacks and swaps."),
    _rule("NEK-SOUL-TRANSFER", 3470, "Soul Transfer", "灵魂转移", (1292248, 1295085), failure=(_signal(1295085, "damage"),), opportunity=(_signal(1292248, "begincast"),), expectation="Avoid the Soul Transfer line."),
    _rule("NEK-PYRE", 3470, "Hungering Pyre", "噬灭烈焰", (1289855, 1294933, 1289875), failure=(_signal(1294933, "damage"),), success=(_signal(1289855, "damage"),), expectation="Share Hungering Pyre instead of receiving Slithering Flame."),
    _rule("NEK-WELL-DEATH", 3470, "Soulcoil Well", "盘魂之井", (1285623, 1299988, 1311788, 1290361), evaluation="observation", expectation="Do not die while affected by the Soulcoil Well."),
    _rule("NEK-DROWNED", 3470, "Grasping Depths", "紧攫深渊", (1293212, 1300235), difficulties=(5,), evaluation="observation", expectation="Resolve each Grasping Depths instance."),
    _rule("NEK-CURSE", 3470, "Soulcoiler's Curse", "盘魂者诅咒", (1300238,), difficulties=(5,), failure=(_signal(1300238, "cast"),), opportunity=(_signal(1300238, "begincast"),), evaluation="interrupt", expectation="Interrupt Soulcoiler's Curse."),
    _rule("NEK-SWIRLING", 3470, "Swirling Spirit", "盘旋精魂", (1300239,), difficulties=(5,), failure=(_signal(1300239, "damage"),), expectation="Avoid Swirling Spirit."),

    # Entombed Sentinels
    _rule("SENT-DOMINANCE", 3445, "Ula'tek's Dominance", "乌拉泰克的统御", (1290189, 1290193), evaluation="observation", expectation="Track each dominance interval."),
    _rule("SENT-COAGULATION", 3445, "Venom Coagulation", "毒液凝块", (1284251, 1284257, 1284258), evaluation="observation", expectation="Defeat each coagulation before additional Contaminate ticks."),
    _rule("SENT-DROPLETS", 3445, "Toxic Droplets", "剧毒水滴", (1284434, 1284451, 1284452), failure=(_signal(1284452, "damage"),), opportunity=(_signal(1284434, "cast"),), success=(_signal(1284451, "damage"),), scope="team", expectation="Squish Toxic Droplets before Noxious Blast."),
    _rule("SENT-BLIGHTED", 3445, "Blighted Blood", "凋零之血", (1284483, 1284471), evaluation="observation", expectation="Dispel Blighted Blood before expiry when required."),
    _rule("SENT-LIVING", 3445, "Living Venom", "活体毒液", (1284209,), difficulties=(4, 5), failure=(_signal(1284209, "damage"),), expectation="Avoid Living Venom projectiles."),
    _rule("SENT-BLOOD-POOL", 3445, "Blood Venom", "鲜血毒液", (1284210,), difficulties=(4, 5), failure=(_signal(1284210, "applydebuff", "damage"),), expectation="Do not stand in Blood Venom."),
    _rule("SENT-MIASMA", 3445, "Unstable Miasma", "不稳定的瘴气", (1288232, 1288260, 1288282, 1288297), evaluation="observation", expectation="Track soak participants and Clinging Murk stacks."),
    _rule("SENT-TANK", 3445, "Empowering Slam and Bloodvenom Injection", "强化猛击与鲜血毒液注射", (1284458, 1284459, 1284487, 1284491, 1310126), evaluation="observation", expectation="Track tank targets and stacks."),
    _rule("SENT-MARKS", 3445, "Mark of Acid and Mark of Blood", "酸液印记与鲜血印记", (1284500, 1284506), evaluation="observation", expectation="Track mark stacks and overlap."),
    _rule("SENT-HELICAL", 3445, "Helical Toxins", "螺旋毒素", (1284588, 1284606, 1284590, 1284941), failure=(_signal(1284941, "damage"),), opportunity=(_signal(1284590, "applydebuff"),), success=(_signal(1284590, "removedebuff"),), evaluation="helical", expectation="Pair compatible Helical Toxins; Cultivated Burst is an observed failed pairing."),
    _rule("SENT-PROTOVENOM", 3445, "Shifting Protovenom", "变幻的原型毒液", (1296878, 1296880, 1296882, 1296962), difficulties=(5,), failure=(_signal(1296962, "damage"),), expectation="Pair compatible protovenom; avoid Protovenom Eruption."),

    # Vashnik the Malignant
    _rule("VASH-FANGS", 3455, "Dripping Fangs", "滴毒之牙", (1280935, 1280934), evaluation="observation", expectation="Track tank applications and swaps."),
    _rule("VASH-FROTH", 3455, "Plague Froth", "瘟疫泡沫", (1281913, 1281925, 1295798), evaluation="observation", expectation="Track Plague Froth targets and damage without treating the marked player as an anomaly."),
    _rule("VASH-BURST", 3455, "Malignant Burst", "恶性爆发", (1280189,), failure=(_signal(1280189, "cast", "damage"),), scope="team", expectation="Defeat Living Venom before Malignant Burst completes."),
    _rule("VASH-SIPHON", 3455, "Siphoning Infection", "虹吸感染", (1295224, 1295380, 1295229, 1314178), evaluation="observation", expectation="Track resolution time and nearby helpers."),
    _rule("VASH-UMBRAL", 3455, "Umbral Ejection", "幽影喷射", (1286737,), failure=(_signal(1286737, "damage"),), expectation="Avoid Umbral Ejection."),
    _rule("VASH-STYGIAN", 3455, "Stygian Burst", "冥河爆发", (1294994, 1302489), failure=(_signal(1302489, "damage"),), expectation="Avoid Stygian Burst."),
    _rule("VASH-SURGE", 3455, "Caustic Surge", "腐蚀涌动", (1285979,), difficulties=(4, 5), evaluation="observation", expectation="Do not overlap two Caustic Surge sources."),
    _rule("VASH-CATALYST", 3455, "Malignant Catalyst", "恶性催化剂", (1282516, 1282602, 1282616), difficulties=(4, 5), failure=(_signal(1282616, "damage"),), opportunity=(_signal(1282516, "begincast", "cast"),), success=(_signal(1282602, "damage"),), scope="team", expectation="Share Malignant Catalyst."),
    _rule("VASH-MALIGNANCE", 3455, "Malignance", "恶念", (1304459,), difficulties=(5,), failure=(_signal(1304459, "cast", "damage"),), opportunity=(_signal(1304459, "begincast"),), scope="team", expectation="Defeat each Malignant Totem before Malignance completes."),
    _rule("VASH-EXPLODING", 3455, "Exploding Infection", "爆炸感染", (1295173, 1295209), evaluation="observation", expectation="Track Exploding Infection damage without inferring distance responsibility."),

    # The Lost Explorers
    _rule("LOST-ICEBOUND", 3497, "Icebound Flames", "冰封烈焰", (1286922,), failure=(_signal(1286922, "cast", "damage", "applydebuff"),), opportunity=(_signal(1286922, "begincast"),), evaluation="interrupt", expectation="Interrupt Icebound Flames."),
    _rule("LOST-JUNK", 3497, "Throw Junk", "投掷垃圾", (1291935, 1306127), failure=(_signal(1291935, "damage"), _signal(1306127, "damage")), expectation="Avoid thrown junk."),
    _rule("LOST-RELIC", 3497, "Relic Rupture", "遗物爆裂", (1310028, 1310027), failure=(_signal(1310028, "cast"), _signal(1310027, "damage")), scope="team", expectation="Clear Useless Junk before Relic Rupture."),
    _rule("LOST-ASCENSION", 3497, "Final Ascension", "最终扬升", (1296535, 1296975, 1297022, 1292779, 1292780), failure=(_signal(1292779, "cast"), _signal(1292780, "damage")), success=(_signal(1296975), _signal(1297022)), scope="team", expectation="Use Disgusting Fish before Final Ascension completes."),
    _rule("LOST-EYES", 3497, "Evil Eyes", "邪眼", (1292764,), failure=(_signal(1292764, "damage"),), expectation="Avoid Evil Eyes."),
    _rule("LOST-SHELL", 3497, "Shell Spin", "旋壳", (1291918,), failure=(_signal(1291918, "applydebuff", "refreshdebuff"),), expectation="Avoid Shell Spin."),
    _rule("LOST-VOLLEY", 3497, "Frostfire Volley", "霜火连射", (1295952, 1297648, 1297649), difficulties=(4, 5), failure=(_signal(1295952, "damage"), _signal(1297648, "damage"), _signal(1297649, "damage")), expectation="Avoid Elemental Explosion and opposing ground effects."),
    _rule("LOST-THUD", 3497, "Mighty Thud", "巨力重击", (1296133, 1300237), evaluation="observation", expectation="Track Mighty Thud sharing without inferring a fixed threshold."),
    _rule("LOST-AFTERSHOCK", 3497, "Aftershock", "余震", (1310500,), difficulties=(4, 5), failure=(_signal(1310500, "damage"),), expectation="Avoid Aftershock."),
    _rule("LOST-SURPRISE", 3497, "Explosive Surprise", "爆炸惊喜", (1296247, 1299947, 1305844, 1297650, 1305618), difficulties=(4, 5), failure=(_signal(1296247, "damage"), _signal(1299947, "damage"), _signal(1305844, "damage"), _signal(1297650, "damage", "applydebuff"), _signal(1305618, "damage")), expectation="Avoid Explosive Surprise effects."),
    _rule("LOST-DEFENSE", 3497, "United Defense", "联合防御", (1297646,), difficulties=(4, 5), evaluation="observation", expectation="Track United Defense duration."),

    # Sszorak
    _rule("SSZ-RAVAGE", 3420, "Ravage", "劫掠", (1277002, 1277101, 1277105), opportunity=(_signal(1277002, "cast"),), evaluation="observation", expectation="Track Ravage targets and repeated tank applications."),
    _rule("SSZ-TEMPEST", 3420, "Tempest", "风暴", (1287072, 1287083), failure=(_signal(1287083, "applydebuff", "damage"),), opportunity=(_signal(1287072, "cast"),), expectation="Avoid Tempest."),
    _rule("SSZ-CLAWS", 3420, "Caustic Claws", "腐蚀利爪", (1305998, 1296667), difficulties=(4, 5), failure=(_signal(1305998, "damage"), _signal(1296667, "applydebuff", "damage")), expectation="Avoid Caustic Claws and Caustic Residue."),
    _rule("SSZ-CROSSWINDS", 3420, "Raging Crosswinds", "狂怒侧风", (1285419, 1285425, 1285453, 1297096, 1297111, 1285616), evaluation="observation", expectation="Track marked players and collateral Crosswinds hits."),
    _rule("SSZ-TURBULENT", 3420, "Turbulent Gusts", "湍流阵风", (1285447,), opportunity=(_signal(1285447, "applydebuff"),), success=(_signal(1285447, "removedebuff"),), evaluation="turbulent", expectation="Opposite gust markers remove in pairs; unpaired removals are reported as facts."),
    _rule("SSZ-FURY", 3420, "Serpent's Fury", "毒蛇之怒", (1297367, 1305621, 1297414, 1299592, 1296898), difficulties=(5,), failure=(_signal(1296898),), scope="team", expectation="Resolve Serpent's Fury before Unbound Ferocity."),
    _rule("SSZ-VIRULENCE", 3420, "Virulence", "剧毒", (1297707, 1299899, 1312189, 1300089), difficulties=(5,), failure=(_signal(1300089, "damage"),), expectation="Remove Virulence without spreading it."),

    # The Twin Fangs
    _rule("TF-GLOBULE", 3421, "Caustic Globule", "腐蚀液滴", (1289994, 1289201, 1290338), failure=(_signal(1290338, "damage"),), opportunity=(_signal(1289994, "cast"),), success=(_signal(1289201, "cast", "damage"),), scope="team", expectation="Catch every Caustic Globule before it ruptures."),
    _rule("TF-ETERNAL", 3421, "Eternal Venom", "永恒毒液", (1290336, 1290480), difficulties=(5,), evaluation="observation", expectation="Keep Eternal Venom below the current ten-stack death threshold."),
    _rule("TF-SPIT", 3421, "Corrosive Spit", "腐蚀唾液", (1291478, 1293295), failure=(_signal(1293295, "damage"),), opportunity=(_signal(1291478, "begincast"),), expectation="Stop Corrosive Spit before it hits a player."),
    _rule("TF-DEPTHS", 3421, "Stir the Depths", "搅动深渊", (1290956, 1292807), failure=(_signal(1292807, "applydebuff", "damage"),), opportunity=(_signal(1290956, "cast"),), expectation="Avoid waves from Stir the Depths."),
    _rule("TF-GROUND", 3421, "Venom ground effects", "毒液场地效果", (1294293, 1294605, 1306872, 1306876, 1292552, 1306925, 1308556, 1309471), failure=(_signal(1294605, "damage", "applydebuff"), _signal(1306872, "damage"), _signal(1306876, "damage"), _signal(1292552, "damage"), _signal(1306925, "damage"), _signal(1309471, "damage", "applydebuff")), expectation="Avoid persistent venom ground effects."),
    _rule("TF-ICHOR", 3421, "Coiling Ichor", "盘卷脓液", (1290814, 1290878), evaluation="observation", expectation="Track Coiling Ichor marks and damage; the carrier cannot be inferred from damage alone."),
    _rule("TF-BREAKER", 3421, "Stone Breaker", "碎石击", (1289092, 1310371, 1289153, 1289154), failure=(_signal(1289153, "damage"), _signal(1289154, "damage")), opportunity=(_signal(1289092, "cast"),), success=(_signal(1310371, "damage"),), scope="team", expectation="Share Stone Breaker."),
    _rule("TF-FEAST", 3421, "Ravenous Feast", "贪婪盛宴", (1290516, 1290662), failure=(_signal(1290662, "damage"),), opportunity=(_signal(1290516, "cast"),), scope="team", expectation="Meet the current Ravenous Feast share count."),
    _rule("TF-BULWARK", 3421, "Barbed Bulwark", "倒刺壁垒", (1303378, 1307363, 1307538), difficulties=(5,), failure=(_signal(1307363, "damage"), _signal(1307538, "damage")), expectation="Break Barbed Bulwark before resolving the globule."),
    _rule("TF-VISCERAL", 3421, "Visceral Burst", "脏腑爆裂", (1308385, 1308386), difficulties=(5,), failure=(_signal(1308385, "cast"), _signal(1308386, "damage")), opportunity=(_signal(1308385, "begincast"),), evaluation="interrupt", expectation="Interrupt Visceral Burst."),
    _rule("TF-TAINTED", 3421, "Tainted Blood", "污血", (1310099, 1310102, 1310105), difficulties=(5,), failure=(_signal(1310105, "damage"),), scope="team", expectation="Heal the Tainted Blood absorb before Tainted Burst."),
    _rule("TF-RANGED", 3421, "Missing melee target", "近战目标缺失", (1295107, 1295115), failure=(_signal(1295107, "cast", "damage"), _signal(1295115, "cast", "damage")), scope="team", expectation="Keep a valid melee target on each boss."),

    # The Coiled Altar
    _rule("ALTAR-GROUND", 3429, "Noxious and Defiled Ground", "剧毒之地与亵渎大地", (1283290, 1298591), failure=(_signal(1283290, "damage"), _signal(1298591, "damage")), expectation="Avoid Noxious and Defiled Ground."),
    _rule("ALTAR-DELUGE", 3429, "Toxic Deluge", "剧毒洪流", (1299960,), failure=(_signal(1299960, "damage"),), expectation="Avoid Toxic Deluge impacts."),
    _rule("ALTAR-VENOM", 3429, "Volatile Venom", "烈性毒液", (1282419, 1282288, 1282403, 1299781), evaluation="observation", expectation="Track Volatile Venom carriers and splash victims."),
    _rule("ALTAR-RUPTURE", 3429, "Venom Rupture", "毒液爆裂", (1299838,), evaluation="observation", expectation="Track Venom Rupture events and stacks."),
    _rule("ALTAR-GUILLOTINE", 3429, "Guillotine", "处斩", (1283485, 1283489, 1283594, 1283606), failure=(_signal(1283606, "damage"),), opportunity=(_signal(1283489, "cast"),), scope="team", expectation="Use the latest encounter rule: at least three players share Guillotine."),
    _rule("ALTAR-SEVER", 3429, "Sever", "撕裂", (1299680, 1299684, 1301690), evaluation="observation", expectation="Track Sever targets; the intended tank hit is not an anomaly."),
    _rule("ALTAR-AXE", 3429, "Axegrinder", "碎斧", (1285017,), difficulties=(4, 5), failure=(_signal(1285017, "applydebuff", "damage"),), verified=(4,), expectation="Avoid Axegrinder."),
    _rule("ALTAR-DREADMARCH", 3429, "Dreadmarch", "恐惧行军", (1285643, 1297445, 1285911, 1307009), failure=(_signal(1307009, "damage", "applydebuff"),), verified=(3, 4), expectation="Do not let a Manifestation of Dread reach its target."),
    _rule("ALTAR-RESONANCE", 3429, "Malevolent Resonance", "恶毒共鸣", (1310732,), difficulties=(5,), failure=(_signal(1310732, "damage", "applydebuff"),), verified=(), expectation="Keep Manifestations of Dread apart."),
    _rule("ALTAR-SOUL-SEVER", 3429, "Soul Sever", "灵魂撕裂", (1286620, 1307959, 1312630, 1286837), evaluation="observation", verified=(3, 4), expectation="Track Soul Sever targets and Gravebound stacks."),
    _rule("ALTAR-WAIL", 3429, "Wail of Terror", "恐惧哀嚎", (1286399,), difficulties=(4, 5), failure=(_signal(1286399, "cast"),), opportunity=(_signal(1286399, "begincast"),), evaluation="interrupt", verified=(4,), expectation="Interrupt Wail of Terror."),
    _rule("ALTAR-NIGHTFALL", 3429, "Eternal Nightfall", "永恒夜幕", (1286912, 1286918, 1286947), failure=(_signal(1286918, "cast", "damage"),), opportunity=(_signal(1286918, "begincast"),), scope="team", verified=(3, 4), expectation="Break Veil of Twilight and interrupt Eternal Nightfall."),
    _rule("ALTAR-GLOOMBOMB", 3429, "Gloombomb", "幽暗炸弹", (1310881, 1310882, 1310883), difficulties=(4, 5), evaluation="observation", verified=(4,), expectation="Track marked players and Gloombomb damage; simultaneous bombs make carrier attribution ambiguous."),
    _rule("ALTAR-FRAGMENTS", 3429, "Spirit Erasure and Reclaim Essence", "精魂抹除与收回精华", (1287722, 1287718), evaluation="observation", verified=(3, 4), expectation="Track erased and reclaimed fragments."),
    _rule("ALTAR-SOULBOUND", 3429, "Soulbound", "灵魂绑定", (1309987, 1309995), failure=(_signal(1309987), _signal(1309995)), scope="team", verified=(3, 4), expectation="Defeat the Soulbound bosses together."),
    _rule("ALTAR-MUTATION", 3429, "Virulent Mutation", "烈毒变异体", (1310544, 1310498, 1310013), difficulties=(5,), evaluation="observation", verified=(5,), expectation="Track mutation carriers and Tainted Blood."),
    _rule("ALTAR-SHIELD", 3429, "Spirit Shield", "灵魂之盾", (1309105, 1310882), difficulties=(5,), evaluation="observation", verified=(), expectation="Use Gloombomb to remove Spirit Shield."),
    _rule("ALTAR-GRIM", 3429, "Grim Guillotine", "冷酷处斩", (1299266, 1299267, 1299296, 1299301, 1307652, 1309940), failure=(_signal(1299301, "damage"),), scope="team", verified=(3, 4), expectation="Share Grim Guillotine under the latest encounter rule."),
    _rule("ALTAR-BLIGHTED", 3429, "Blighted Sever", "凋零撕裂", (1307279,), evaluation="observation", verified=(4,), expectation="Track Blighted Sever targets; the intended tank hit is not an anomaly."),

    # Ula'tek. Mythic rules are defined but intentionally unverified and never emit anomalies.
    _rule("ULATEK-WAVES", 3492, "Caustic Waves", "腐蚀浪潮", (1292403,), failure=(_signal(1292403, "damage", "applydebuff"),), verified=(3, 4), expectation="Avoid Caustic Waves."),
    _rule("ULATEK-IMPACTS", 3492, "Call of the Serpent, Virulent Spit, and Falling Debris", "毒蛇呼唤、剧毒喷吐与落石", (1304012, 1302982, 1286885), failure=(_signal(1304012, "damage"), _signal(1302982, "damage"), _signal(1286885, "damage")), verified=(3, 4), expectation="Avoid impact locations."),
    _rule("ULATEK-SHELL", 3492, "Malignant Shell", "恶性甲壳", (1295360, 1297213), evaluation="observation", verified=(3, 4), expectation="Track egg carriers and carry duration."),
    _rule("ULATEK-MEMBRANE", 3492, "Putrid Membrane", "腐臭薄膜", (1301268,), evaluation="observation", verified=(3, 4), expectation="Track fully hatched Blightscale Viper outcomes."),
    _rule("ULATEK-WRATH", 3492, "Mother's Wrath", "蛇母之怒", (1298367, 1298369, 1298417, 1298418, 1300938), evaluation="observation", verified=(3, 4), expectation="Keep an intended tank in melee range."),
    _rule("ULATEK-RAGE", 3492, "Unchecked Rage and Rattler Slam", "无羁之怒与响尾猛击", (1286945, 1299206), failure=(_signal(1286945, "damage"), _signal(1299206, "damage")), scope="team", verified=(3, 4), expectation="Keep valid melee targets on Ula'tek and the Gore Rattle."),
    _rule("ULATEK-COILS", 3492, "Spectral Coils", "幽魂盘卷", (1299010, 1300685, 1287265), evaluation="observation", verified=(4,), expectation="Use the current required share count for Spectral Coils."),
    _rule("ULATEK-DOOMSCALE", 3492, "Doomscale Shell", "厄鳞外壳", (1300312, 1300314, 1303410, 1305775), failure=(_signal(1305775, "cast", "damage"),), success=(_signal(1303410, "applydebuff", "applybuff"),), scope="team", verified=(3, 4), expectation="Interrupt Doomscale gestation before Dread Roar."),
    _rule("ULATEK-MALICE", 3492, "Malice", "恶意", (1290779, 1290991), failure=(_signal(1290779, "cast"), _signal(1290991, "damage")), opportunity=(_signal(1290779, "begincast"),), evaluation="interrupt", verified=(4,), expectation="Interrupt Malice."),
    _rule("ULATEK-FANGS", 3492, "Grasping Fangs", "攫取毒牙", (1301117, 1311611, 1311612, 1311600, 1311609), difficulties=(4, 5), evaluation="observation", verified=(4,), expectation="Track Grasping Fangs resolution time."),
    _rule("ULATEK-STING", 3492, "Petrifying Sting", "石化钉刺", (1303414,), difficulties=(4, 5), evaluation="observation", verified=(4,), expectation="Track Petrifying Sting victims; WCL cannot identify the original target reliably."),
    _rule("ULATEK-CRY", 3492, "Anguished Cry", "痛苦哀嚎", (1305650,), failure=(_signal(1305650, "cast"),), opportunity=(_signal(1305650, "begincast"),), evaluation="interrupt", verified=(4,), expectation="Interrupt Anguished Cry."),
    _rule("ULATEK-THRASH", 3492, "Desperate Thrash", "绝望鞭笞", (1305709,), evaluation="observation", verified=(4,), expectation="Track Desperate Thrash targets; the intended tank hit is not an anomaly."),
    _rule("ULATEK-ECHOES", 3492, "Vicious Echoes", "险恶回音", (1291700, 1310764), difficulties=(4, 5), failure=(_signal(1291700, "cast", "damage"), _signal(1310764, "cast", "damage")), opportunity=(_signal(1291700, "begincast"), _signal(1310764, "begincast")), evaluation="interrupt", verified=(4,), expectation="Interrupt Vicious Echoes."),
    _rule("ULATEK-BITE", 3492, "Serpent's Bite", "毒蛇之咬", (1295905, 1295838, 1288879, 1306119, 1318329), difficulties=(4, 5), failure=(_signal(1306119, "applydebuff"), _signal(1318329, "damage")), opportunity=(_signal(1295905, "cast"),), verified=(4,), expectation="Resolve Serpent's Bite before Calcified Corpse."),
    _rule("ULATEK-PURGE", 3492, "Volatile Purge", "易爆清除", (1312967, 1306086, 1305878, 1316356, 1316357), difficulties=(4, 5), evaluation="observation", verified=(4,), expectation="Track Volatile Purge marks and damage; simultaneous purges make carrier attribution ambiguous."),
    _rule("ULATEK-CORPSE", 3492, "Calcified Corpse", "钙化尸骸", (1306119, 1318329), difficulties=(4, 5), failure=(_signal(1306119, "applydebuff"), _signal(1318329, "damage")), verified=(4,), expectation="Prevent Calcified Corpse."),
    _rule("ULATEK-PREY", 3492, "Circling Prey and Acidic Expulsion", "盘绕猎物与酸液喷发", (1301510, 1315341, 1313531), failure=(_signal(1301510, "damage"), _signal(1315341, "damage"), _signal(1313531, "damage")), verified=(3, 4), expectation="Avoid Circling Prey and Acidic Expulsion."),
    _rule("ULATEK-NOXIOUS", 3492, "Noxious Shell", "剧毒之壳", (1307612, 1307635, 1312150), difficulties=(5,), failure=(_signal(1307635, "damage", "applydebuff"),), verified=(), expectation="Keep Noxious Shell carriers apart."),
    _rule("ULATEK-INCUBATION", 3492, "Toxic Incubation", "剧毒孵化", (1299757, 1299764, 1302842), difficulties=(5,), evaluation="observation", verified=(), expectation="Track player intercepts and Mother's Boon impacts."),
    _rule("ULATEK-GESTATION", 3492, "Mass Gestation and Revenge", "群体孕育与复仇", (1308038, 1307941), difficulties=(5,), failure=(_signal(1308038), _signal(1307941)), scope="team", verified=(), expectation="Avoid Mass Gestation and incorrect Doomscale kill order."),
)


def rules_for(encounter_id: int, difficulty_id: int) -> tuple[MechanicRule, ...]:
    return tuple(
        rule
        for rule in RULES
        if rule.encounter_id == encounter_id and difficulty_id in rule.difficulties
    )


def encounter_name(encounter_id: int) -> tuple[str, str] | None:
    return next(
        ((name_en, name_zh) for current_id, name_en, name_zh in RAID_ENCOUNTERS if current_id == encounter_id),
        None,
    )


def build_filter_expression(rules: tuple[MechanicRule, ...]) -> str:
    ability_ids = sorted({ability_id for rule in rules for ability_id in rule.ability_ids})
    clauses = [f"ability.id = {ability_id}" for ability_id in ability_ids]
    clauses.extend(('type = "death"', 'type = "interrupt"', 'type = "dispel"'))
    return " or ".join(clauses)
