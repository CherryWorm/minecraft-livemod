package gm.conduit.mobs;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import gm.conduit.dimensions.Dimensions;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.world.level.Level;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Everything that makes a slot into a particular mob, from the current release.
 *
 * @param spawn null if this mob never appears on its own, such as a boss a module summons
 * @param mind null for the great majority of mobs, which just run on plain code
 * @param sounds what it sounds like idle, hurt and dying, by those names, for whichever of them it has its own
 * @param flying whether it flies, and never comes down unless it wants to
 * @param knockbackResistance how much of a hit's push it ignores, from 0 to 1
 * @param glowing the parts of its model drawn at full brightness
 */
public record MobDefinition(String model, String behaviour, double health, double damage, double speed, double followRange,
		double armor, float width, float height, Spawn spawn, Mind mind, String display, Map<String, SoundEvent> sounds,
		boolean flying, double knockbackResistance, List<String> glowing) {

	/**
	 * @param light dark, bright or any
	 * @param dimension which one it appears in
	 */
	public record Spawn(int weight, String light, List<String> biomes, int minY, int maxY, int cap, boolean underground, ResourceKey<Level> dimension) {}

	static MobDefinition parse(JsonObject json) {
		Spawn spawn = null;
		if (json.has("spawn")) {
			JsonObject raw = json.getAsJsonObject("spawn");
			List<String> biomes = new ArrayList<>();
			if (raw.has("biomes")) {
				JsonArray list = raw.getAsJsonArray("biomes");
				list.forEach(item -> biomes.add(item.getAsString()));
			}
			spawn = new Spawn(raw.get("weight").getAsInt(), raw.get("light").getAsString(), biomes,
					raw.get("minY").getAsInt(), raw.get("maxY").getAsInt(), raw.get("cap").getAsInt(),
					raw.has("underground") && raw.get("underground").getAsBoolean(),
					Dimensions.levelKey(raw.has("dimension") ? raw.get("dimension").getAsString() : null));
		}
		Map<String, SoundEvent> sounds = new HashMap<>();
		if (json.has("sounds")) {
			json.getAsJsonObject("sounds").asMap().forEach((kind, sound) ->
					sounds.put(kind, SoundEvent.createVariableRangeEvent(Identifier.parse(sound.getAsString()))));
		}
		List<String> glowing = new ArrayList<>();
		if (json.has("glowing")) {
			json.getAsJsonArray("glowing").forEach(part -> glowing.add(part.getAsString()));
		}
		return new MobDefinition(json.get("model").getAsString(), json.get("behaviour").getAsString(),
				json.get("health").getAsDouble(), json.get("damage").getAsDouble(), json.get("speed").getAsDouble(),
				json.has("followRange") ? json.get("followRange").getAsDouble() : 24.0,
				json.has("armor") ? json.get("armor").getAsDouble() : 0.0,
				json.get("width").getAsFloat(), json.get("height").getAsFloat(), spawn,
				json.has("mind") ? Mind.parse(json.getAsJsonObject("mind")) : null,
				json.has("display") ? json.get("display").getAsString() : "",
				sounds,
				json.has("flying") && json.get("flying").getAsBoolean(),
				json.has("knockback_resistance") ? json.get("knockback_resistance").getAsDouble() : 0.0,
				glowing);
	}
}
