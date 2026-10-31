package gm.companion;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.resources.Identifier;

public final class Companion implements ClientModInitializer {
	private static final ModuleHost HOST = new ModuleHost();

	public static ModuleHost host() {
		return HOST;
	}

	@Override
	public void onInitializeClient() {
		PayloadTypeRegistry.clientboundPlay().register(ModulePayloads.Chunk.TYPE, ModulePayloads.Chunk.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(ModulePayloads.Unload.TYPE, ModulePayloads.Unload.CODEC);

		ClientPlayNetworking.registerGlobalReceiver(ModulePayloads.Chunk.TYPE, (payload, context) -> HOST.onChunk(payload));
		ClientPlayNetworking.registerGlobalReceiver(ModulePayloads.Unload.TYPE, (payload, context) -> HOST.unload(payload.moduleId()));

		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath("gm", "modules"), HOST::renderHud);
		ClientTickEvents.END_CLIENT_TICK.register(HOST::tick);
		ClientPlayConnectionEvents.DISCONNECT.register((handler, client) -> HOST.unloadAll());
	}
}
