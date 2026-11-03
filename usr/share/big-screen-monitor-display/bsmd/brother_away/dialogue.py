"""Dialogue library, organised by context.

All lines are original writing for the character. Catchphrase references
("AWAAAAAY!", "perplecto", "morô?") are a cultural homage and can be turned
off (``ba_catchphrases``); new lines are never presented as real quotes of
the artist. The Brazilian Portuguese text is the canonical voice and lives
in ``locale/pt.po``; msgids are English for the translation pipeline.

Humour levels: F = family, C = classic, A = adult (sarcastic, never
offensive or discriminatory). "classic" includes F and C; "adult" all.
"""

import random

from ..i18n import _, N_

CATCHPHRASE = "catch"

LINES = {
    "awaaay": [(N_("AWAAAAAY!"), "F", CATCHPHRASE)],
    "perplexed": [(N_("I'm perplexed!"), "F", CATCHPHRASE),
                  (N_("I am... perplexed. Very perplexed."), "C", CATCHPHRASE)],
    "final": [(N_("AWAAAAAY! NOT EVEN ON A DESERT ISLAND DO I GET A MINUTE OF PEACE, MORÔ?!"), "F", CATCHPHRASE)],
    "coconut_first": [(N_("Hm. A coconut. Coincidence."), "F", None),
                      (N_("Coconut falls, man sleeps. Nature's contract."), "C", None)],
    "coconut_hit": [(N_("This palm tree has a personal problem with me!"), "F", None),
                    (N_("Hey! I saw that! Don't play innocent!"), "F", None),
                    (N_("Are you throwing coconuts at a citizen?"), "C", None),
                    (N_("I pay no rent here, but I demand respect!"), "C", None),
                    (N_("My lawyer will hear about this. As soon as I find a lawyer on this island."), "A", None)],
    "palm_argue": [(N_("Don't you shake your leaves at me!"), "F", None),
                   (N_("Answer me like a tree!"), "C", None),
                   (N_("I'd file a complaint, but the ombudsman is a coconut."), "A", None)],
    "shark_reflection": [(N_("Why are my glasses showing a fin?"), "F", None)],
    "shark_run": [(N_("SHAAARK!"), "F", None), (N_("Not today, fish with teeth!"), "C", None)],
    "shark_argue": [(N_("I came to take a bath, not to attend a meeting with predators!"), "F", None),
                    (N_("Laughing at me? You don't even have a neck!"), "C", None),
                    (N_("Ocean, we need to talk about your friends."), "C", None)],
    "raft_build": [(N_("One more plank and goodbye, island!"), "F", None),
                   (N_("Naval engineering, island edition."), "C", None),
                   (N_("Today I leave this island! Today!"), "F", None)],
    "raft_done": [(N_("It's ready! The finest vessel of the South Atlantic!"), "F", None)],
    "raft_broken": [(N_("My naval engineering was sabotaged by nature!"), "F", None),
                    (N_("A wave. One small wave. Unbelievable."), "C", None)],
    "ufo_wake": [(N_("Who's there?!"), "F", None), (N_("Turn off that light, I'm sleeping!"), "C", None)],
    "ufo_speech": [(N_("Listen here, interplanetary citizens!"), "F", None),
                   (N_("Humanity invented the hammock, the barbecue and the Monday nap. Respect that!"), "F", None),
                   (N_("You came all this way to abduct the only guy without a phone?"), "C", None),
                   (N_("We have problems enough down here. Get in line!"), "A", None)],
    "ufo_win": [(N_("They ran away! The Earth is safe! You're welcome!"), "F", None)],
    "philosophy": [(N_("If a coconut falls and nobody is under it... is it still personal?"), "F", None),
                   (N_("Is the horizon the end of the world, or the beginning of another island?"), "F", None),
                   (N_("Man is an island. And I'm a man on an island. That's a lot of island."), "C", None),
                   (N_("The sea comes, the sea goes. Nobody asks the sea where it's going."), "C", None)],
    "philosophy_ask": [(N_("Do you get what I'm saying, morô?"), "F", CATCHPHRASE),
                       (N_("Do you get what I'm saying?"), "F", "plain")],
    "philosophy_agree": [(N_("See? Even the palm tree agrees."), "F", None)],
    "crab": [(N_("This citizen walks sideways because he won't face reality!"), "F", None),
             (N_("Give me back my glasses, sideways bandit!"), "F", None)],
    "no_glasses": [(N_("Without glasses I can see everything... and I didn't like it."), "C", None),
                   (N_("Too much reality. Where are my glasses?"), "F", None)],
    "gull": [(N_("That was my lunch! Flying thief!"), "F", None),
             (N_("Fishing for hours to feed an air pirate."), "C", None)],
    "fish_wait": [(N_("Bite, little fish. I have a story to tell."), "F", None),
                  (N_("Today the fish wins nothing!"), "F", None)],
    "fish_caught": [(N_("Look at this beauty!"), "F", None), (N_("Dinner is served!"), "F", None)],
    "fish_lost": [(N_("He gave the bait back! The nerve!"), "F", None)],
    "bottle_found": [(N_("A message in a bottle!"), "F", None)],
    "bottle_read": [(N_("'Dear reader: you are on an island.' Thanks, very helpful!"), "F", None),
                    (N_("It's a bill. Even here they find me!"), "C", None),
                    (N_("'Help!' Ha! Get in line, buddy."), "C", None)],
    "rain": [(N_("I asked for water, not a complete change of ocean!"), "F", None),
             (N_("Even the sky is crying over my situation."), "C", None)],
    "storm": [(N_("Who ordered the storm? It wasn't me!"), "F", None)],
    "night": [(N_("Even the stars are watching me, and nobody comes to get me!"), "F", None),
              (N_("The moon is the only one here who understands me."), "F", None)],
    "morning": [(N_("Good morning, island! Same problems as yesterday?"), "F", None)],
    "mermaid_call": [(N_("Hey, mermaid! Come here, I need to complain about the service!"), "F", None)],
    "mermaid_gone": [(N_("She left. Nobody listens to complaints anymore."), "F", None)],
    "ship_missed": [(N_("Did I miss something?"), "F", None), (N_("I have a feeling I missed something."), "C", None)],
    "dance": [(N_("Island style!"), "F", None), (N_("The crab can't dance like this!"), "F", None)],
    "palm_talk": [(N_("You know, palm tree, you're a good listener."), "F", None),
                  (N_("Don't tell anyone, but you're my best friend here."), "F", None)],
    "idle": [(N_("Peace... finally."), "F", None), (N_("Nobody bothering me. Suspicious."), "C", None)],
    "heat": [(N_("This sun is overclocked!"), "F", None),
             (N_("It's hotter than a processor compiling a kernel!"), "C", None)],
    "hot_shade": [(N_("I'm going to the shade before I melt."), "F", None)],
    "ram": [(N_("Where did all this stuff come from? I didn't buy any of this!"), "F", None)],
    "disk": [(N_("No more room in the chest! I'll have to delete some coconuts."), "F", None)],
    "gpu": [(N_("Even the volcano is rendering something!"), "F", None)],
    "treasure": [(N_("A treasure! I'm rich! ...and still on an island."), "F", None)],
    "mirror": [(N_("Who is this handsome castaway?"), "F", None)],
    "sandcastle_lost": [(N_("My castle! Years of architecture!"), "F", None)],
}

LEVELS = {"family": {"F"}, "classic": {"F", "C"}, "adult": {"F", "C", "A"}}


class Dialogue:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.recent = []

    def line(self, context, settings):
        allowed = LEVELS.get(settings.get("ba_humor", "classic"), LEVELS["classic"])
        catch = settings.get("ba_catchphrases", True)
        options = [(text, tag) for text, level, tag in LINES.get(context, [])
                   if level in allowed and (catch or tag != CATCHPHRASE) and (not catch or tag != "plain")]
        if not options:
            return None
        fresh = [opt for opt in options if opt[0] not in self.recent] or options
        text = self.rng.choice(fresh)[0]
        self.recent = (self.recent + [text])[-12:]
        return _(text)
