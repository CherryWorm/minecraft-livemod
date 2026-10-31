package gm.conduit.mixin;

import com.mojang.authlib.GameProfile;
import gm.conduit.pack.PackStatus;
import net.minecraft.network.protocol.common.ServerboundResourcePackPacket;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerCommonPacketListenerImpl;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ServerCommonPacketListenerImpl.class)
abstract class ServerCommonPacketListenerImplMixin {
	@Shadow @Final protected MinecraftServer server;

	@Shadow protected abstract GameProfile playerProfile();

	@Inject(method = "handleResourcePackResponse", at = @At("HEAD"))
	private void conduit$recordPackStatus(ServerboundResourcePackPacket packet, CallbackInfo ci) {
		// The handler runs twice: once on the network thread, then again on the server thread.
		if (this.server.isSameThread()) {
			PackStatus.record(this.playerProfile().name(), packet.action());
		}
	}
}
