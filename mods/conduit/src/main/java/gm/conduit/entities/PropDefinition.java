package gm.conduit.entities;

import com.google.gson.JsonObject;

/**
 * Everything that makes a slot into a particular prop, from the current release.
 *
 * @param clickable whether players can click on it at all, which costs it a hitbox
 */
public record PropDefinition(String model, float width, float height, boolean clickable) {
	static PropDefinition parse(JsonObject json) {
		return new PropDefinition(json.get("model").getAsString(), json.get("width").getAsFloat(), json.get("height").getAsFloat(),
				json.has("clickable") && json.get("clickable").getAsBoolean());
	}
}
