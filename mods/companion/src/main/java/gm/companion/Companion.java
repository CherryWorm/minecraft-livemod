package gm.companion;

import com.mojang.brigadier.Command;
import gm.companion.guide.Guide;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommands;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.network.chat.Component;
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

		PayloadTypeRegistry.clientboundPlay().register(KnownRecipes.Part.TYPE, KnownRecipes.Part.CODEC);

		ClientPlayNetworking.registerGlobalReceiver(ModulePayloads.Chunk.TYPE, (payload, context) -> HOST.onChunk(payload));
		ClientPlayNetworking.registerGlobalReceiver(ModulePayloads.Unload.TYPE, (payload, context) -> HOST.unload(payload.moduleId()));
		// Never sent. Listening for it is how the server tells this companion from one too old for inventory hooks.
		PayloadTypeRegistry.clientboundPlay().register(ModulePayloads.InventoryHooksSupported.TYPE, ModulePayloads.InventoryHooksSupported.CODEC);
		ClientPlayNetworking.registerGlobalReceiver(ModulePayloads.InventoryHooksSupported.TYPE, (payload, context) -> {});
		ClientPlayNetworking.registerGlobalReceiver(KnownRecipes.Part.TYPE, (payload, context) -> KnownRecipes.receive(payload));
		PanelClient.register();
		EffectClient.register();
		if (FabricLoader.getInstance().isModLoaded("patchouli")) {
			Guide.register();
		}

		HudElementRegistry.addLast(Identifier.fromNamespaceAndPath("gm", "modules"), HOST::renderHud);
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> InventoryScreens.attach(HOST, screen));
		ClientTickEvents.END_CLIENT_TICK.register(HOST::tick);
		ClientPlayConnectionEvents.DISCONNECT.register((handler, client) -> {
			HOST.unloadAll();
			KnownRecipes.forget();
			PanelClient.forget();
			EffectClient.forget();
		});
		ClientLifecycleEvents.CLIENT_STOPPING.register(client -> HOST.unloadAll());

		// A friend can always turn this off on their own machine, with no permission from anyone.
		ClientCommandRegistrationCallback.EVENT.register((dispatcher, buildContext) -> dispatcher.register(
				ClientCommands.literal("companion")
						.then(ClientCommands.literal("off").executes(context -> {
							HOST.setTurnedOff(true);
							context.getSource().sendFeedback(Component.translatableWithFallback("companion.modules_off", "Modules are off on this computer."));
							return Command.SINGLE_SUCCESS;
						}))
						.then(ClientCommands.literal("on").executes(context -> {
							HOST.setTurnedOff(false);
							context.getSource().sendFeedback(Component.translatableWithFallback("companion.modules_on", "Modules are on. They'll load next time you join."));
							return Command.SINGLE_SUCCESS;
						}))));
	}
}
