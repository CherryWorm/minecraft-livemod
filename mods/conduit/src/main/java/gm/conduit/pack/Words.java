package gm.conduit.pack;

import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.contents.TranslatableContents;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;

import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * What's said to players, in whatever language each one's game is set to. Almost everything goes out as a key with its English beside it, so
 * a client finds it in its own copy of the pack and shows the English if it can't, and a player changing language needs nothing from the server.
 *
 * <p>A few things only take plain text, like a panel's words or a book's title. For those, the server reads the same language files and goes by
 * what the player's game told it, which means it won't change until they next open it. It has no language files for vanilla's own names, so those stay in English there.
 */
public final class Words {
	private static final Pattern PLACE = Pattern.compile("%(?:(\\d+)\\$)?([s%])");

	private Words() {}

	/** Says something in a player's own language, once it reaches their game. It's in English if their pack has no translation of it, or they've no pack. */
	public static MutableComponent say(String key, String english, Object... args) {
		return Component.translatableWithFallback(key, english, args);
	}

	/** The language this world has words for that's closest to what their game is set to. Every kind of German reads the same words. */
	public static String languageOf(ServerPlayer player) {
		String language = player.clientInformation().language();
		return language.startsWith("de_") ? "de_de" : language;
	}

	/** What a key says for this player, for what can only take plain text. */
	public static String shown(Player player, String key, String english, Object... args) {
		String language = player instanceof ServerPlayer serverPlayer ? languageOf(serverPlayer) : ServerNames.ENGLISH;
		return format(language, ServerNames.in(language, key, english), args);
	}

	/** Anything that can go out as a message, written out in one language, as a client would show it. */
	public static String flatten(Component component, String language) {
		StringBuilder text = new StringBuilder();
		if (component.getContents() instanceof TranslatableContents translatable) {
			text.append(format(language, ServerNames.in(language, translatable.getKey(), translatable.getFallback() != null ? translatable.getFallback() : translatable.getKey()), translatable.getArgs()));
		} else {
			component.getContents().visit(piece -> {
				text.append(piece);
				return Optional.empty();
			});
		}
		component.getSiblings().forEach(sibling -> text.append(flatten(sibling, language)));
		return text.toString();
	}

	/** The game's own way of filling in values, which is only %s, %1$s and %%. */
	private static String format(String language, String template, Object... args) {
		Matcher place = PLACE.matcher(template);
		StringBuilder text = new StringBuilder();
		int next = 0;
		while (place.find()) {
			String value = "%";
			if (place.group(2).equals("s")) {
				int index = place.group(1) != null ? Integer.parseInt(place.group(1)) - 1 : next++;
				value = index >= 0 && index < args.length ? (args[index] instanceof Component component ? flatten(component, language) : String.valueOf(args[index])) : "";
			}
			place.appendReplacement(text, Matcher.quoteReplacement(value));
		}
		place.appendTail(text);
		return text.toString();
	}
}
