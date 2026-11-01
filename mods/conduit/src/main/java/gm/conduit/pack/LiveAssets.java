package gm.conduit.pack;

import eu.pb4.polymer.resourcepack.api.PolymerResourcePackUtils;
import gm.conduit.slots.NeutralSlots;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Builds the slot part of the resource pack. Every slot gets a placeholder so the client never logs a
 * missing model, then anything in live-assets/ overrides it. Regenerating the pack picks up new files,
 * so art can change without restarting the server.
 */
public final class LiveAssets {
	private static final Path ROOT = Path.of("live-assets");
	private static final String PLACEHOLDER_MODEL = "{\"parent\":\"minecraft:block/stone\"}";
	private static final String PLACEHOLDER_ITEM_MODEL = "{\"parent\":\"minecraft:item/generated\",\"textures\":{\"layer0\":\"minecraft:item/barrier\"}}";

	private LiveAssets() {}

	public static void register() {
		PolymerResourcePackUtils.RESOURCE_PACK_AFTER_INITIAL_CREATION_EVENT.register(builder -> {
			for (String id : NeutralSlots.blockIds()) {
				builder.addData("assets/gm/models/block/" + id + ".json", bytes(PLACEHOLDER_MODEL));
				builder.addData("assets/gm/items/" + id + ".json", itemDefinition("gm:block/" + id));
			}
			for (String model : NeutralSlots.stateModels()) {
				builder.addData("assets/gm/models/block/" + model + ".json", bytes(PLACEHOLDER_MODEL));
			}
			for (String id : NeutralSlots.itemIds()) {
				builder.addData("assets/gm/models/item/" + id + ".json", bytes(PLACEHOLDER_ITEM_MODEL));
				builder.addData("assets/gm/items/" + id + ".json", itemDefinition("gm:item/" + id));
			}
			if (Files.isDirectory(ROOT)) {
				builder.copyFromPath(ROOT);
			}
		});
	}

	private static byte[] itemDefinition(String model) {
		return bytes("{\"model\":{\"type\":\"minecraft:model\",\"model\":\"" + model + "\"}}");
	}

	private static byte[] bytes(String text) {
		return text.getBytes(StandardCharsets.UTF_8);
	}
}
