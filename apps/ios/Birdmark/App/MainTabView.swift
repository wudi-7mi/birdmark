import SwiftUI

struct MainTabView: View {
    var body: some View {
        TabView {
            SharedPhotosView()
                .tabItem {
                    Label("共享", systemImage: "photo.on.rectangle")
                }

            UploadView()
                .tabItem {
                    Label("上传", systemImage: "square.and.arrow.up")
                }

            CollectionView()
                .tabItem {
                    Label("图鉴", systemImage: "leaf")
                }

            ProfileView()
                .tabItem {
                    Label("我的", systemImage: "person.crop.circle")
                }
        }
    }
}
