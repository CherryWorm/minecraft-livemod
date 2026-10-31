package gm.conduit.mobs;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Everything that makes a slot into a particular mob, from the current release.
 *
 * @param spawn null if this mob never appears on its own, such as a boss a module summons
 * @param mind null for the great majority of mobs, which just run on plain code
 */
public record MobDefinition(String model, String behaviour, double health, double damage, double speed, double followRange,
		double armor, float width, float height, Spawn spawn, Mind mind, String display) {

	/** @param light dark, bright or any */
	public record Spawn(int weight, String light, List<String> biomes, int minY, int maxY, int cap, boolean underground) {}

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
					raw.has("underground") && raw.get("underground").getAsBoolean());
		}
		return new MobDefinition(json.get("model").getAsString(), json.get("behaviour").getAsString(),
				json.get("health").getAsDouble(), json.get("damage").getAsDouble(), json.get("speed").getAsDouble(),
				json.has("followRange") ? json.get("followRange").getAsDouble() : 24.0,
				json.has("armor") ? json.get("armor").getAsDouble() : 0.0,
				json.get("width").getAsFloat(), json.get("height").getAsFloat(), spawn,
				json.has("mind") ? Mind.parse(json.getAsJsonObject("mind")) : null,
				json.has("display") ? json.get("display").getAsString() : "");
	}
}
