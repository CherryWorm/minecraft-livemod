package gm.conduit.entities;

import com.google.gson.JsonObject;
import net.minecraft.resources.Identifier;
import net.minecraft.sounds.SoundEvent;

import java.util.HashMap;
import java.util.Map;

/**
 * Everything that makes a slot into a particular projectile, from the current release. A release writes speed and gravity per
 * second, and they're kept here per tick, which is what the game moves things by.
 *
 * @param trail the particle it leaves behind it, or null for none
 * @param lifetime ticks of flight before it goes out by itself
 * @param sounds what it sounds like going off and hitting something, by those names, for whichever of them it has its own
 */
public record ProjectileDefinition(String model, double damage, double speed, double gravity, int lifetime, float width, float height,
		Identifier trail, int ticksBetweenShots, Map<String, SoundEvent> sounds) {
	private static final int TICKS_PER_SECOND = 20;

	static ProjectileDefinition parse(JsonObject json) {
		return new ProjectileDefinition(json.get("model").getAsString(), json.get("damage").getAsDouble(),
				json.get("speed").getAsDouble() / TICKS_PER_SECOND,
				json.has("gravity") ? json.get("gravity").getAsDouble() / (TICKS_PER_SECOND * TICKS_PER_SECOND) : 0.0,
				(int) (json.get("lifetime").getAsDouble() * TICKS_PER_SECOND),
				json.get("width").getAsFloat(), json.get("height").getAsFloat(),
				json.has("trail") ? Identifier.parse(json.get("trail").getAsString()) : null,
				(int) Math.round(TICKS_PER_SECOND / json.get("shots_per_second").getAsDouble()),
				sounds(json));
	}

	static Map<String, SoundEvent> sounds(JsonObject json) {
		Map<String, SoundEvent> sounds = new HashMap<>();
		if (json.has("sounds")) {
			json.getAsJsonObject("sounds").asMap().forEach((kind, sound) ->
					sounds.put(kind, SoundEvent.createVariableRangeEvent(Identifier.parse(sound.getAsString()))));
		}
		return sounds;
	}
}
