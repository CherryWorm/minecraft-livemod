package gm.conduit.mobs;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * What a mob with a mind may do, from the current release. A model picks from these and plain code checks every
 * choice, so nothing said to a mob can get it to do anything that isn't listed here.
 *
 * @param raw sent along with each event, because it also holds the character, which only the agent reads
 * @param stash what it can hand over, and to whom. Limits are per player and per kind of mob, so killing one doesn't refill it
 * @param teaches knowledge it can pass on, and the trust that takes
 * @param loves items worth more trust than other gifts
 * @param leadsTo blocks it knows the way to
 * @param moves what it can choose from in a fight, every fightSeconds
 */
public record Mind(JsonObject raw, Set<String> actions, Set<String> animations, Set<String> sounds, Map<String, Stash> stash, Map<String, Integer> teaches,
		Set<String> loves, List<String> leadsTo, boolean greets, List<String> moves, int fightSeconds) {

	public record Stash(int count, int trust) {}

	static Mind parse(JsonObject json) {
		Map<String, Stash> stash = new HashMap<>();
		if (json.has("stash")) {
			json.getAsJsonArray("stash").forEach(entry -> {
				JsonObject item = entry.getAsJsonObject();
				stash.put(item.get("item").getAsString(), new Stash(item.get("count").getAsInt(), item.has("trust") ? item.get("trust").getAsInt() : 1));
			});
		}
		Map<String, Integer> teaches = new HashMap<>();
		if (json.has("teaches")) {
			json.getAsJsonObject("teaches").entrySet().forEach(entry -> teaches.put(entry.getKey(), entry.getValue().getAsInt()));
		}
		return new Mind(json, new HashSet<>(strings(json, "actions")), new HashSet<>(strings(json, "animations")), new HashSet<>(strings(json, "sounds")), stash, teaches,
				new HashSet<>(strings(json, "loves")), strings(json, "leads_to"), json.has("greets") && json.get("greets").getAsBoolean(), strings(json, "moves"),
				json.has("fight_seconds") ? json.get("fight_seconds").getAsInt() : 10);
	}

	private static List<String> strings(JsonObject json, String field) {
		List<String> list = new ArrayList<>();
		if (json.has(field)) {
			JsonArray items = json.getAsJsonArray(field);
			items.forEach(item -> list.add(item.getAsString()));
		}
		return list;
	}
}
