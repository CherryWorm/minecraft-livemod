You make the top of the web page where this Minecraft server's players follow how their world is coming along: a picture and a few words. `theme.md` in your folder says what the world is.

The picture is a wide banner. Write a Python script that draws it with Pillow, in pixel art, and save the result as `banner.png` in your current folder. Draw it at 480x120 and save it enlarged to exactly 1920x480 with nearest-neighbour scaling, so its pixels stay crisp. Look at your work by reading the image, and redraw until you're proud of it. Three or four rounds are normal.

What makes one good:
- One wide scene with a strong mood: a sky, a horizon and the lie of the land, in layers that read at a glance. It should feel like this world and could only be this one.
- A small, deliberate palette taken from the theme, shaded with a few placed tones, not smooth gradients or noise.
- No text at all, and leave the left third calm, because words get set over it.

Use only Pillow and numpy, and work only in this folder.

Then give these in the required JSON:
- `name`: the name of this world's theme, in a few words, as a title. It's for people who've chosen to see spoilers.
- `text`: two or three short paragraphs that make someone want to play this world, about its mood and what kind of story it tells. It's for people who've chosen to see spoilers, so it can name the theme, but leave out how anything is made or found.
- `safe_name`: a title for the same world, in a few words, for people avoiding spoilers. It gives no hint of what's in the world.
- `tease`: one or two short sentences for those same people, which build curiosity about the mood and nothing else.
- `accent`: one colour from your palette as `#rrggbb`, which the page uses for its lines and tabs. Choose one that stands out on both a dark and a light background.

`safe_name` and `tease` are shown to everyone who opens the page, and most of them haven't found much of this world yet. So neither can name or hint at the theme, a place, a material, a creature, a machine, an event or a goal, and neither can use a word from `name`. Words that could describe almost any world are fine.

Nothing here can quote or refer to any one player.
